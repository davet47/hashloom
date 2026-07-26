"""The hashloom shared verification-cache server.

A minimal stdlib HTTP server wrapping one `SqliteStore`, exposing exactly the four
team-portable Store operations `LayeredStore` needs -- get/record a verdict,
get/put a blob -- as a tiny JSON API behind a bearer token. A team points each
developer's `.hashloom/config.json` `{"shared": {...}}` at one of these, so a unit
verified green once is served to everyone (see docs/hosted-store.md).

Auth is scoped by verb: GET is a read, POST is a publish. With only `--token`,
that one token does both (the original single-token deployment). Add
`--publish-token` to split the roles: reads accept either token (publish
implies read), publishes require the publish token -- so CI writes greens and
a laptop with the read token can only consume them. A read token on a publish
route is 403 `read_only`; an unrecognized token is 401 `unauthorized`.

It is intentionally NOT a `hashloom` subcommand (the 5-CLI surface is fixed); run it
as a separate operational process:

    python -m hashloom.cache_server --db cache.db --token SECRET [--publish-token SECRET2] [--host H --port P]

Single-threaded by design: a `SqliteStore` holds one sqlite connection (not
thread-safe), and the verdict/blob writes are idempotent upserts, so
last-writer-wins is fine for the MVP. A future throughput upgrade is
`ThreadingHTTPServer` + a per-thread or lock-guarded connection; CAS and
concurrent-writer ordering are deferred (docs/hosted-store.md #4).
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote

from .store import SqliteStore

DEFAULT_PORT = 8770


class CacheServer(HTTPServer):
    """An HTTPServer that holds the store and expected token(s) for the handler."""

    def __init__(
        self,
        addr: tuple[str, int],
        store: SqliteStore,
        token: str,
        publish_token: str | None = None,
    ):
        super().__init__(addr, _Handler)
        self.store = store
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
        if not self._authed():
            return self._error(401, "unauthorized", "missing or invalid bearer token")
        store = self.server.store
        if self.path.startswith("/verification/"):
            row = store.get_verification(unquote(self.path[len("/verification/"):]))
            return self._send(200, row) if row is not None else self._error(404, "not_found", "no such verdict")
        if self.path.startswith("/blob/"):
            content = store.get_blob(unquote(self.path[len("/blob/"):]))
            return self._send(200, {"content": content}) if content is not None else self._error(404, "not_found", "no such blob")
        return self._error(404, "not_found", "unknown route")

    def do_POST(self) -> None:
        if not self._authed(publish=True):
            # a valid read token on a publish route is a scope problem, not an
            # identity problem — tell the client which one it has
            if self._authed():
                return self._error(403, "read_only", "publishing requires the publish token")
            return self._error(401, "unauthorized", "missing or invalid bearer token")
        store = self.server.store
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
            store.record_verification(key, name, status, body.get("summary", ""))
            return self._send(204)
        if self.path == "/blob":
            content = body.get("content")
            if not isinstance(content, str):
                return self._error(400, "bad_request", "blob content must be a string")
            return self._send(200, {"hash": store.put_blob(content)})
        return self._error(404, "not_found", "unknown route")


def serve(
    db: str,
    token: str,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    publish_token: str | None = None,
) -> None:
    store = SqliteStore(db, check_same_thread=False)  # used on the serve_forever thread
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
