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
from .config import resolve_pycache_trust, resolve_timeout
from .errors import HashloomError
from .project import find_root
from .remote import build_store


def build_server(
    root: Path | None = None, python: str | None = None, pycache_trust: bool | None = None
) -> FastMCP:
    root = find_root(root)
    store = build_store(root)  # local, or LayeredStore over a shared cache if configured
    # the toolchain override is resolved per-language inside verify_one, so a
    # project can mix Python and Go contracts
    timeout = resolve_timeout(root)
    trust = resolve_pycache_trust(root, override=pycache_trust)
    mcp = FastMCP("hashloom")

    def _respond(tool: str, fn) -> dict:
        try:
            result = fn()
        except HashloomError as e:
            result = e.to_dict()
        except Exception as e:  # never leak a stack trace to the agent
            result = HashloomError("internal", f"{type(e).__name__}: {e}").to_dict()
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
        dependent whose cached verification this change invalidates; inferred
        (machine-derived, unreviewed) contracts among them are flagged."""
        return _respond("put_contract", lambda: api.put_contract(root, store, name, yaml_text))

    @mcp.tool()
    def get_dependents(name: str, transitive: bool = False) -> dict:
        """Blast-radius query: contracts that depend on `name` (direct, or the
        full transitive closure), with their current hashes. Entries not yet
        human-reviewed carry `inferred: true` (advisory — never an error)."""
        return _respond("get_dependents", lambda: api.get_dependents(root, store, name, transitive))

    @mcp.tool()
    def verify(names: list[str], radius: bool = False) -> dict:
        """Verify contracts against their pytest node IDs. Returns per-unit
        cached-pass / pass / fail with a ≤40-token failure summary. Runs
        pytest only for units whose (contract, impl, deps) hash key is not
        already green in the cache. `radius=true` widens each name to its full
        blast radius (itself plus every transitive dependent); the top-level
        `ok` is the hard pass/fail to gate on. An `inferred` list names any
        unconfirmed contracts a verdict rests on."""
        return _respond(
            "verify",
            lambda: api.verify(
                root, store, names, python=python, timeout=timeout, pycache_trust=trust, radius=radius
            ),
        )

    @mcp.tool()
    def status() -> dict:
        """Project health: dirty contracts, stale verifications, cache hit-rate,
        and cumulative token counters for every tool response."""
        return _respond("status", lambda: api.status(root, store))

    return mcp


def serve(root: Path | None = None, python: str | None = None, pycache_trust: bool | None = None) -> None:
    build_server(root, python=python, pycache_trust=pycache_trust).run()  # stdio transport
