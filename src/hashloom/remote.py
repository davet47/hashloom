"""The `RemoteStore` client: the team-portable Store methods over HTTP.

`LayeredStore` (shared.py) only ever calls four methods on its shared store --
`get_verification`, `record_verification`, `get_blob`, `put_blob` -- so a remote
backend need implement only those (plus `close`). This client talks to a hashloom
`cache_server` over a tiny JSON HTTP API with a bearer token, using the stdlib
only.

It is deliberately **fault-tolerant**: any transport error degrades to a cache
miss (`get_*` -> None) or a silent no-op (`record`/`put`), so a shared-store
outage never breaks a local verify. The local single-process path stays the
default; the shared cache is an optimisation, not a dependency.
"""

from __future__ import annotations

import hashlib
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import resolve_shared_store
from .project import db_path
from .store import SqliteStore, Store


class RemoteStore:
    def __init__(self, url: str, token: str, timeout: float = 5.0):
        self._base = url.rstrip("/")
        self._token = token
        self._timeout = timeout

    @classmethod
    def from_config(cls, cfg: dict) -> RemoteStore:
        return cls(cfg["url"], cfg["token"])

    # -- the four team-portable methods -------------------------------------

    def get_verification(self, key: str) -> dict | None:
        st, body = self._request("GET", "/verification/" + urllib.parse.quote(key, safe=""))
        return body if st == 200 and isinstance(body, dict) else None

    def record_verification(self, key: str, contract_name: str, status: str, summary: str) -> None:
        # fire-and-forget; _request swallows any transport error. The layer has
        # already written the verdict locally, so a publish failure loses nothing.
        self._request("POST", "/verification", {
            "key": key, "contract_name": contract_name, "status": status, "summary": summary,
        })

    def get_blob(self, blob_hash: str) -> str | None:
        st, body = self._request("GET", "/blob/" + urllib.parse.quote(blob_hash, safe=""))
        return body.get("content") if st == 200 and isinstance(body, dict) else None

    def put_blob(self, content: str) -> str:
        self._request("POST", "/blob", {"content": content})
        # the layer uses the *local* hash; return ours regardless of the network
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def close(self) -> None:  # urllib opens no persistent connection
        pass

    # -- transport ----------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict | None]:
        """Return (status, parsed-json-or-None). Never raises: a transport
        failure degrades to (0, None) so callers fall back to local."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self._base + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.status, _read_json(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, None  # 401/404/400 are real statuses, not transport failures
        except (urllib.error.URLError, socket.timeout, OSError, ValueError):
            return 0, None  # unreachable / timeout -> degrade to a miss


def _read_json(raw: bytes) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def build_store(root: Path) -> Store:
    """The local store, wrapped in a `LayeredStore` over a remote shared store
    when `.hashloom/config.json` configures one. The single wrap point shared by
    `hashloom serve` and the CLI -- keeps the 5-tool / 5-CLI surface unchanged."""
    local = SqliteStore(db_path(root))
    cfg = resolve_shared_store(root)
    if cfg is None:
        return local
    from .shared import LayeredStore  # only needed when a shared store is configured

    return LayeredStore(local, RemoteStore.from_config(cfg))
