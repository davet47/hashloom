"""The hashloom shared verification-cache server.

A minimal stdlib HTTP server wrapping one `SqliteStore`, exposing the four
team-portable Store operations `LayeredStore` needs -- get/record a verdict,
get/put a blob -- plus the operator-facing revocation routes, as a tiny JSON
API behind a bearer token. A team points each
developer's `.hashloom/config.json` `{"shared": {...}}` at one of these, so a unit
verified green once is served to everyone (see docs/hosted-store.md).

Auth is scoped by verb: GET is a read, POST is a publish. With only `--token`,
that one token does both (the original single-token deployment). Add
`--publish-token` to split the roles: reads accept either token (publish
implies read), publishes require the publish token -- so CI writes greens and
a laptop with the read token can only consume them. A read token on a publish
route is 403 `read_only`; an unrecognized token is 401 `unauthorized`.

Routes: GET /verification/<key>, GET /blob/<hash>, GET /stale (the revocation
audit listing), POST /verification, POST /blob, and POST /stale -- key-addressed
revocation for greens that were wrong at publish time (flaky passes, env drift
the verification key cannot see). Body: {"keys": [...], "names": [...],
"stale": true|false, "reason": "..."}; names resolve server-side to their
EXISTING keys. The response's `premarked` counts keys tombstoned ahead of
any publish (no row yet — not a failed mark). Revoked keys stay stale under
any publish; {"stale": false} (keys only) is the only restore path. See
docs/hosted-store.md for the runbook.

It is intentionally NOT a `hashloom` subcommand (the 5-CLI surface is fixed); run it
as a separate operational process:

    python -m hashloom.cache_server --db cache.db --token SECRET [--publish-token SECRET2] [--host H --port P]

Threaded requests, serialised storage: a `ThreadingHTTPServer` handles
network IO and JSON concurrently, while one `threading.Lock` guards the
single sqlite connection — so every db write stays a serialised
single-statement commit, exactly the semantics the store comment promises.
Verdict publishes are first-writer-wins (`CacheStore`): duplicates of a
bit-identical run are no-ops, never a `ran_at` refresh or a `stale` reset.
The future throughput upgrade, if a team ever saturates the lock, is WAL +
per-thread connections + bounded busy-retry (docs/hosted-store.md #4).
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from .store import SqliteStore, _now

DEFAULT_PORT = 8770
MAX_STALE_SELECTORS = 1000  # per request: keys given, names given, and keys resolved
SQL_CHUNK = 500  # stay under every SQLite build's host-variable limit (999 pre-3.32)


def _chunks(items: list[str], size: int = SQL_CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


class CacheStore(SqliteStore):
    """The server's store: first-writer-wins publishes, revocable verdicts.

    Two publishes for one verification key are independent runs of a
    bit-identical closure (the key hashes contract, impl, test source,
    toolchain, and the dep closure), so a duplicate must not refresh
    `ran_at` — the verdict is as old as the run that produced it — and must
    not reset `stale`. Blobs are content-addressed INSERT OR IGNORE already.

    Revocation (`mark_stale_keys`) tombstones keys whose green was wrong at
    publish time — a flaky pass, env drift the toolchain identity misses. A
    revoked key stays stale under ANY publish, duplicate or fresh (the
    `stale_marks` EXISTS clause below covers the mark-before-publish
    ordering; DO NOTHING covers the rest). The only un-stale path is an
    explicit authenticated restore — an operator action, not the
    publish-resurrection race first-writer-wins closed. Restore is
    key-addressed only, and tombstone audit records are first-reason-wins,
    so a later name sweep can neither rewrite why a key was originally
    revoked nor lift tombstones it did not create.
    """

    def __init__(self, db_path, check_same_thread: bool = True):
        super().__init__(db_path, check_same_thread=check_same_thread)
        # server-only audit table; IF NOT EXISTS doubles as the migration
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS stale_marks("
            "key TEXT PRIMARY KEY, reason TEXT NOT NULL DEFAULT '', marked_at TEXT NOT NULL)"
        )
        self._conn.commit()

    def record_verification(self, key: str, contract_name: str, status: str, summary: str) -> None:
        self._conn.execute(
            "INSERT INTO verifications(key, contract_name, status, summary, ran_at, stale) "
            "VALUES(?,?,?,?,?, EXISTS(SELECT 1 FROM stale_marks WHERE key=?)) "
            "ON CONFLICT(key) DO NOTHING",
            (key, contract_name, status, summary, _now(), key),
        )
        self._conn.commit()

    def keys_for_names(self, names: list[str]) -> list[str]:
        """The EXISTING keys recorded under these contract names — a name
        sweep marks what is, never what will be (future keys land fresh)."""
        out: list[str] = []
        for chunk in _chunks(names):
            rows = self._conn.execute(
                f"SELECT key FROM verifications WHERE contract_name IN ({','.join('?' * len(chunk))})",
                chunk,
            )
            out.extend(r["key"] for r in rows)
        return out

    def mark_stale_keys(self, keys: list[str], stale: bool = True, reason: str = "") -> int:
        if not keys:
            return 0
        marked = 0
        try:
            if stale:
                marked_at = _now()
                for chunk in _chunks(keys):
                    # first reason wins: a key already revoked keeps its original
                    # audit record through any later sweep that also covers it
                    self._conn.executemany(
                        "INSERT INTO stale_marks(key, reason, marked_at) VALUES(?,?,?) "
                        "ON CONFLICT(key) DO NOTHING",
                        [(k, reason, marked_at) for k in chunk],
                    )
                    cur = self._conn.execute(
                        f"UPDATE verifications SET stale=1 WHERE key IN ({','.join('?' * len(chunk))})", chunk
                    )
                    marked += cur.rowcount
            else:
                for chunk in _chunks(keys):
                    holes = ",".join("?" * len(chunk))
                    self._conn.execute(f"DELETE FROM stale_marks WHERE key IN ({holes})", chunk)
                    cur = self._conn.execute(f"UPDATE verifications SET stale=0 WHERE key IN ({holes})", chunk)
                    marked += cur.rowcount
            self._conn.commit()
        except Exception:
            # a half-mark left pending would be committed by the next unrelated
            # request; roll the whole batch back instead
            self._conn.rollback()
            raise
        return marked

    def stale_listing(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT m.key, m.reason, m.marked_at, v.contract_name, v.ran_at "
            "FROM stale_marks m LEFT JOIN verifications v ON v.key=m.key "
            "UNION ALL "
            "SELECT key, '', NULL, contract_name, ran_at FROM verifications "
            "WHERE stale=1 AND key NOT IN (SELECT key FROM stale_marks) "
            "ORDER BY marked_at",
        )
        return [dict(r) for r in rows]


class CacheServer(ThreadingHTTPServer):
    """A threaded server holding the store, its lock, and the token(s)."""

    # join in-flight request threads in server_close(), so `serve()` may
    # close the store immediately after without a use-after-close
    daemon_threads = False

    def __init__(
        self,
        addr: tuple[str, int],
        store: SqliteStore,
        token: str,
        publish_token: str | None = None,
    ):
        super().__init__(addr, _Handler)
        self.store = store
        self.store_lock = threading.Lock()  # one connection, serialised db work
        self.token = token
        self.publish_token = publish_token  # None -> `token` gates both verbs


class _Handler(BaseHTTPRequestHandler):
    server_version = "hashloom-cache/1"

    # -- helpers ------------------------------------------------------------

    def _send(self, status: int, body: dict | None = None) -> None:
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        self.send_response(status)
        if payload:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def _error(self, status: int, code: str, message: str) -> None:
        self._send(status, {"error": {"code": code, "message": message}})

    def _presented(self) -> str | None:
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return header[len(prefix):] if header.startswith(prefix) else None

    def _authed(self, publish: bool = False) -> bool:
        """Constant-time check against the token(s) the verb accepts.

        Reads accept the read token or the publish token (publish implies
        read); publishes require the publish token when one is configured.
        Both comparisons always run — no short-circuit string equality.
        """
        presented = self._presented()
        if presented is None:
            return False
        is_read = hmac.compare_digest(presented, self.server.token)
        pub = self.server.publish_token
        is_publish = pub is not None and hmac.compare_digest(presented, pub)
        if publish and pub is not None:
            return is_publish
        return is_read or is_publish

    def _read_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return None

    def log_message(self, *args) -> None:  # keep the cache server quiet
        pass

    # -- routes -------------------------------------------------------------

    def do_GET(self) -> None:
        try:
            self._handle_get()
        except Exception as e:  # noqa: BLE001 — never leak a stack trace to a client
            self._error(500, "internal", f"{type(e).__name__}: {e}")

    def do_POST(self) -> None:
        try:
            self._handle_post()
        except Exception as e:  # noqa: BLE001 — never leak a stack trace to a client
            self._error(500, "internal", f"{type(e).__name__}: {e}")

    def _handle_get(self) -> None:
        if not self._authed():
            return self._error(401, "unauthorized", "missing or invalid bearer token")
        store, lock = self.server.store, self.server.store_lock
        if self.path.startswith("/verification/"):
            with lock:
                row = store.get_verification(unquote(self.path[len("/verification/"):]))
            return self._send(200, row) if row is not None else self._error(404, "not_found", "no such verdict")
        if self.path.startswith("/blob/"):
            with lock:
                content = store.get_blob(unquote(self.path[len("/blob/"):]))
            return self._send(200, {"content": content}) if content is not None else self._error(404, "not_found", "no such blob")
        if self.path == "/stale":  # observability is a read: the read token suffices
            with lock:
                rows = store.stale_listing()
            return self._send(200, {"stale": rows})
        return self._error(404, "not_found", "unknown route")

    def _handle_post(self) -> None:
        if not self._authed(publish=True):
            # a valid read token on a publish route is a scope problem, not an
            # identity problem — tell the client which one it has
            if self._authed():
                return self._error(403, "read_only", "publishing requires the publish token")
            return self._error(401, "unauthorized", "missing or invalid bearer token")
        store, lock = self.server.store, self.server.store_lock
        body = self._read_body()
        if not isinstance(body, dict):
            return self._error(400, "bad_request", "expected a JSON object body")
        if self.path == "/verification":
            try:
                key, name, status = body["key"], body["contract_name"], body["status"]
            except (KeyError, TypeError):
                return self._error(400, "bad_request", "missing key/contract_name/status")
            if status != "pass":
                return self._error(400, "only_greens", "the shared cache stores passes only")
            with lock:
                store.record_verification(key, name, status, body.get("summary", ""))
            return self._send(204)
        if self.path == "/blob":
            content = body.get("content")
            if not isinstance(content, str):
                return self._error(400, "bad_request", "blob content must be a string")
            with lock:
                blob_hash = store.put_blob(content)
            return self._send(200, {"hash": blob_hash})
        if self.path == "/stale":
            keys, names = body.get("keys", []), body.get("names", [])
            stale, reason = body.get("stale", True), body.get("reason", "")
            for field, value in (("keys", keys), ("names", names)):
                if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
                    return self._error(400, "bad_request", f"{field} must be a list of non-empty strings")
                if len(value) > MAX_STALE_SELECTORS:
                    return self._error(400, "bad_request", f"at most {MAX_STALE_SELECTORS} {field} per request")
            if not keys and not names:
                return self._error(400, "bad_request", "at least one of keys/names must be non-empty")
            if not isinstance(stale, bool):
                return self._error(400, "bad_request", "stale must be true or false")
            if not isinstance(reason, str):
                return self._error(400, "bad_request", "reason must be a string")
            if not stale and names:
                # restore is key-addressed only: a name here would also lift
                # tombstones this sweep never created (GET /stale lists the keys)
                return self._error(400, "bad_request", "restore takes keys only, not names")
            # resolve + mark under one lock hold, so no publish slips between them
            with lock:
                all_keys = sorted(set(keys) | set(store.keys_for_names(names)))
                if len(all_keys) > MAX_STALE_SELECTORS:
                    return self._error(400, "bad_request", f"refusing to mark more than {MAX_STALE_SELECTORS} keys at once")
                marked = store.mark_stale_keys(all_keys, stale=stale, reason=reason)
            result = {"marked": marked, "keys": len(all_keys)}
            if stale:
                # keys revoked ahead of any publish: no row yet, tombstone only
                result["premarked"] = len(all_keys) - marked
            return self._send(200, result)
        return self._error(404, "not_found", "unknown route")


def serve(
    db: str,
    token: str,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    publish_token: str | None = None,
) -> None:
    store = CacheStore(db, check_same_thread=False)  # request threads serialise via store_lock
    httpd = CacheServer((host, port), store, token, publish_token=publish_token)
    print(f"hashloom cache server on http://{host}:{httpd.server_address[1]}  (db: {db})", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        store.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m hashloom.cache_server",
        description="hashloom shared verification-cache server (operational, not a hashloom subcommand)",
    )
    p.add_argument("--db", default="cache.db", help="sqlite file for the shared cache (default: cache.db)")
    p.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1; use 0.0.0.0 to share)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"bind port (default: {DEFAULT_PORT})")
    p.add_argument(
        "--token",
        default=os.environ.get("HASHLOOM_CACHE_TOKEN"),
        help="bearer token clients must present (or set HASHLOOM_CACHE_TOKEN); "
        "with no --publish-token it grants reads and publishes both",
    )
    p.add_argument(
        "--publish-token",
        default=os.environ.get("HASHLOOM_CACHE_PUBLISH_TOKEN"),
        help="optional second token required to publish (or set HASHLOOM_CACHE_PUBLISH_TOKEN); "
        "when set, --token becomes read-only and this token grants reads and publishes",
    )
    args = p.parse_args(argv)
    if not args.token:
        p.error("a --token (or HASHLOOM_CACHE_TOKEN env var) is required; refusing to run an unauthenticated cache")
    serve(args.db, args.token, host=args.host, port=args.port, publish_token=args.publish_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
