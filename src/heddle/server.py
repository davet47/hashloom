"""MCP server: the five tools over stdio.

Each tool returns structured JSON; errors come back as {error: {code, message,
contract?}}, never stack traces. Token counts for every response accumulate in
the store's counters (visible via `status` — the demo numbers live there).
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import api, tokens
from .config import resolve_python, resolve_timeout
from .errors import HeddleError
from .project import db_path, find_root
from .store import Store


def build_server(root: Path | None = None, python: str | None = None) -> FastMCP:
    root = find_root(root)
    store = Store(db_path(root))
    interp = resolve_python(root, override=python)  # resolved once per session
    timeout = resolve_timeout(root)
    mcp = FastMCP("heddle")

    def _respond(tool: str, fn) -> dict:
        try:
            result = fn()
        except HeddleError as e:
            result = e.to_dict()
        except Exception as e:  # never leak a stack trace to the agent
            result = HeddleError("internal", f"{type(e).__name__}: {e}").to_dict()
        n = tokens.count(json.dumps(result, ensure_ascii=False))
        store.incr(f"tokens.{tool}", n)
        return result

    @mcp.tool()
    def get_contract(name: str) -> dict:
        """Fetch one contract as a compact context packet: the contract body, its
        content hash, one-line signatures of its deps, and the list of callers."""
        return _respond("get_contract", lambda: api.get_contract(root, store, name))

    @mcp.tool()
    def put_contract(name: str, yaml_text: str) -> dict:
        """Create or update a contract (validates shape, rejects unknown deps).
        Writes contracts/<name>.yaml and returns the new hash plus every
        dependent whose cached verification this change invalidates."""
        return _respond("put_contract", lambda: api.put_contract(root, store, name, yaml_text))

    @mcp.tool()
    def get_dependents(name: str, transitive: bool = False) -> dict:
        """Blast-radius query: contracts that depend on `name` (direct, or the
        full transitive closure), with their current hashes."""
        return _respond("get_dependents", lambda: api.get_dependents(root, store, name, transitive))

    @mcp.tool()
    def verify(names: list[str]) -> dict:
        """Verify contracts against their pytest node IDs. Returns per-unit
        cached-pass / pass / fail with a ≤40-token failure summary. Runs
        pytest only for units whose (contract, impl, deps) hash key is not
        already green in the cache."""
        return _respond("verify", lambda: api.verify(root, store, names, python=interp, timeout=timeout))

    @mcp.tool()
    def status() -> dict:
        """Project health: dirty contracts, stale verifications, cache hit-rate,
        and cumulative token counters for every tool response."""
        return _respond("status", lambda: api.status(root, store))

    return mcp


def serve(root: Path | None = None, python: str | None = None) -> None:
    build_server(root, python=python).run()  # stdio transport
