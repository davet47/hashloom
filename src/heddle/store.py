"""SQLite store: contracts, dependency edges, impls, impl-source blobs,
verifications, counters.

The store is derived state — deletable and rebuildable from contracts/ at any
time via `heddle index`.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contracts(
    name TEXT PRIMARY KEY, hash TEXT NOT NULL, yaml TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS edges(
    from_name TEXT NOT NULL, to_name TEXT NOT NULL,           -- from depends on to
    PRIMARY KEY(from_name, to_name));
CREATE TABLE IF NOT EXISTS impls(
    contract_name TEXT PRIMARY KEY, impl_hash TEXT, path TEXT, blob_hash TEXT);
CREATE TABLE IF NOT EXISTS blobs(
    hash TEXT PRIMARY KEY, content TEXT NOT NULL);   -- impl source, content-addressed
CREATE TABLE IF NOT EXISTS impl_hash_cache(
    impl_ref TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL, impl_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS verifications(
    key TEXT PRIMARY KEY, contract_name TEXT NOT NULL, status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '', ran_at TEXT NOT NULL, stale INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS counters(name TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_name);
CREATE INDEX IF NOT EXISTS idx_verifications_contract ON verifications(contract_name);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        # the store is derived, but add new columns in place so an existing
        # store.db from an older heddle keeps working without a manual rebuild
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(impls)")}
        if "blob_hash" not in cols:
            self._conn.execute("ALTER TABLE impls ADD COLUMN blob_hash TEXT")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- contracts ----------------------------------------------------------

    def upsert_contract(self, name: str, chash: str, yaml_text: str) -> None:
        self._conn.execute(
            "INSERT INTO contracts(name, hash, yaml, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET hash=excluded.hash, yaml=excluded.yaml, updated_at=excluded.updated_at",
            (name, chash, yaml_text, _now()),
        )
        self._conn.commit()

    def get_contract(self, name: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM contracts WHERE name=?", (name,)).fetchone()

    def contract_names(self) -> list[str]:
        return [r["name"] for r in self._conn.execute("SELECT name FROM contracts ORDER BY name")]

    def contract_hashes(self) -> dict[str, str]:
        return {r["name"]: r["hash"] for r in self._conn.execute("SELECT name, hash FROM contracts")}

    def delete_contract(self, name: str) -> None:
        self._conn.execute("DELETE FROM contracts WHERE name=?", (name,))
        self._conn.execute("DELETE FROM edges WHERE from_name=?", (name,))
        self._conn.execute("DELETE FROM impls WHERE contract_name=?", (name,))
        self._conn.commit()

    # -- edges --------------------------------------------------------------

    def set_deps(self, name: str, deps: list[str]) -> None:
        self._conn.execute("DELETE FROM edges WHERE from_name=?", (name,))
        self._conn.executemany(
            "INSERT OR IGNORE INTO edges(from_name, to_name) VALUES(?,?)",
            [(name, d) for d in deps],
        )
        self._conn.commit()

    def deps_of(self, name: str) -> list[str]:
        return [r["to_name"] for r in self._conn.execute(
            "SELECT to_name FROM edges WHERE from_name=? ORDER BY to_name", (name,))]

    def dependents_of(self, name: str, transitive: bool = False) -> list[str]:
        """Contracts that depend on `name` (directly, or transitively closed)."""
        seen: set[str] = set()
        frontier = [name]
        while frontier:
            rows = self._conn.execute(
                f"SELECT DISTINCT from_name FROM edges WHERE to_name IN ({','.join('?' * len(frontier))})",
                frontier,
            ).fetchall()
            frontier = [r["from_name"] for r in rows if r["from_name"] not in seen]
            seen.update(frontier)
            if not transitive:
                break
        return sorted(seen)

    def transitive_deps(self, name: str) -> list[str]:
        seen: set[str] = set()
        frontier = [name]
        while frontier:
            rows = self._conn.execute(
                f"SELECT DISTINCT to_name FROM edges WHERE from_name IN ({','.join('?' * len(frontier))})",
                frontier,
            ).fetchall()
            frontier = [r["to_name"] for r in rows if r["to_name"] not in seen]
            seen.update(frontier)
        return sorted(seen)

    # -- impls + content-addressed impl-source blobs ------------------------

    def upsert_impl(
        self, contract_name: str, impl_hash: str | None, path: str | None, blob_hash: str | None = None
    ) -> None:
        # blob_hash is COALESCEd: a caller without the source (verify) passes None
        # and must not clear a blob a prior index/put_contract recorded
        self._conn.execute(
            "INSERT INTO impls(contract_name, impl_hash, path, blob_hash) VALUES(?,?,?,?) "
            "ON CONFLICT(contract_name) DO UPDATE SET impl_hash=excluded.impl_hash, path=excluded.path, "
            "blob_hash=COALESCE(excluded.blob_hash, impls.blob_hash)",
            (contract_name, impl_hash, path, blob_hash),
        )
        self._conn.commit()

    def get_impl(self, contract_name: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM impls WHERE contract_name=?", (contract_name,)).fetchone()

    def put_blob(self, content: str) -> str:
        """Store impl source under its content hash (idempotent); return the hash."""
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self._conn.execute("INSERT OR IGNORE INTO blobs(hash, content) VALUES(?,?)", (h, content))
        self._conn.commit()
        return h

    def get_blob(self, blob_hash: str) -> str | None:
        row = self._conn.execute("SELECT content FROM blobs WHERE hash=?", (blob_hash,)).fetchone()
        return row["content"] if row is not None else None

    # -- impl hash cache (keyed by file identity; speeds up status) ----------

    def get_cached_impl_hash(self, impl_ref: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM impl_hash_cache WHERE impl_ref=?", (impl_ref,)).fetchone()

    def put_cached_impl_hash(self, impl_ref: str, mtime_ns: int, size: int, impl_hash: str) -> None:
        self._conn.execute(
            "INSERT INTO impl_hash_cache(impl_ref, mtime_ns, size, impl_hash) VALUES(?,?,?,?) "
            "ON CONFLICT(impl_ref) DO UPDATE SET mtime_ns=excluded.mtime_ns, size=excluded.size, impl_hash=excluded.impl_hash",
            (impl_ref, mtime_ns, size, impl_hash),
        )
        self._conn.commit()

    # -- verifications ------------------------------------------------------

    def record_verification(self, key: str, contract_name: str, status: str, summary: str) -> None:
        self._conn.execute(
            "INSERT INTO verifications(key, contract_name, status, summary, ran_at, stale) VALUES(?,?,?,?,?,0) "
            "ON CONFLICT(key) DO UPDATE SET status=excluded.status, summary=excluded.summary, "
            "ran_at=excluded.ran_at, stale=0",
            (key, contract_name, status, summary, _now()),
        )
        self._conn.commit()

    def get_verification(self, key: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM verifications WHERE key=?", (key,)).fetchone()

    def mark_stale(self, contract_names: list[str]) -> int:
        if not contract_names:
            return 0
        cur = self._conn.execute(
            f"UPDATE verifications SET stale=1 WHERE contract_name IN ({','.join('?' * len(contract_names))})",
            contract_names,
        )
        self._conn.commit()
        return cur.rowcount

    def stale_verifications(self) -> list[str]:
        return sorted({r["contract_name"] for r in self._conn.execute(
            "SELECT DISTINCT contract_name FROM verifications WHERE stale=1")})

    # -- counters -----------------------------------------------------------

    def incr(self, name: str, by: int = 1) -> None:
        self._conn.execute(
            "INSERT INTO counters(name, value) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET value=value+excluded.value",
            (name, by),
        )
        self._conn.commit()

    def counters(self) -> dict[str, int]:
        return {r["name"]: r["value"] for r in self._conn.execute("SELECT name, value FROM counters")}

    def reset_counters(self) -> None:
        self._conn.execute("DELETE FROM counters")
        self._conn.commit()
