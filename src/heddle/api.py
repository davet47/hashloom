"""The five tool implementations, as plain functions over (root, store).

server.py exposes these over MCP; the CLI and benchmark call them directly.
Every function either returns a JSON-able dict or raises HeddleError.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .config import resolve_python
from .contract import contract_hash, diff_contracts, parse_contract
from .errors import HeddleError, unknown_name
from .langs import adapter_for
from .project import atomic_write_text, case_collision, contract_lock, safe_contract_path
from .store import Store
from .verify import clear_pycache, verification_key, verify_one


# responses carry 12-hex-char hashes — plenty to compare against, a quarter of
# the tokens; full hashes never leave the store/verification keys
SHORT = 12


def _short(h: str) -> str:
    return h[:SHORT]


def _load(store: Store, name: str) -> tuple[dict, str]:
    row = store.get_contract(name)
    if row is None:
        raise unknown_name("unknown_contract", name, store.contract_names())
    return yaml.safe_load(row["yaml"]), row["hash"]


def get_contract(root: Path, store: Store, name: str) -> dict:
    """The ~300-token context packet: contract + hash + dep signatures + callers."""
    data, chash = _load(store, name)
    deps = []
    for dep in data.get("deps", []):
        dep_data, dep_hash = _load(store, dep)
        deps.append({"name": dep, "signature": dep_data["signature"], "hash": _short(dep_hash)})
    return {
        "name": name,
        "hash": _short(chash),
        # name and deps would duplicate the envelope — the deps array below
        # carries them with signatures attached
        "contract": {k: v for k, v in data.items() if k not in ("name", "deps")},
        "deps": deps,
        "callers": store.dependents_of(name),
    }


def put_contract(root: Path, store: Store, name: str, yaml_text: str) -> dict:
    """Validate, write to contracts/, reindex the one unit, invalidate dependents."""
    data = parse_contract(yaml_text, expect_name=name)
    known = set(store.contract_names()) | {name}
    for dep in data.get("deps", []):
        if dep == name:
            raise HeddleError("invalid_shape", f"'{name}' cannot depend on itself", contract=name)
        if dep not in known:
            raise unknown_name("unknown_dep", dep, sorted(known - {name}), contract=name)

    new_hash = contract_hash(data)
    target = safe_contract_path(root, name)  # also refuses a name that escapes contracts/
    collision = case_collision(target)
    if collision is not None:
        raise HeddleError(
            "name_collision",
            f"'{name}' collides with existing contract file '{collision}' on a case-insensitive filesystem",
            contract=name,
        )
    # lock the name so concurrent put_contract on it can't interleave the file
    # write and the store update and leave the two disagreeing
    with contract_lock(root, name):
        old = store.get_contract(name)
        changed = old is None or old["hash"] != new_hash
        # what changed vs the previously stored contract: empty for a new unit or
        # a cosmetic-only edit, using the same normalisation as the hash
        diff = diff_contracts(yaml.safe_load(old["yaml"]), data) if old is not None else {}

        atomic_write_text(target, yaml_text)
        store.upsert_contract(name, new_hash, yaml_text)
        store.set_deps(name, data.get("deps", []))
        if "impl" in data:
            adapter = adapter_for(data["impl"])
            try:
                ihash = adapter.impl_hash(root, data["impl"], contract=name)
            except HeddleError:
                ihash = None
            store.upsert_impl(name, ihash, data["impl"].partition("::")[0])

        invalidated: list[str] = []
        if changed:
            invalidated = store.dependents_of(name, transitive=True)
            store.mark_stale([name, *invalidated])
    result = {"name": name, "hash": _short(new_hash), "changed": changed, "invalidated": invalidated}
    if diff:
        result["diff"] = diff
    return result


def get_dependents(root: Path, store: Store, name: str, transitive: bool = False) -> dict:
    """Blast-radius query: who is invalidated if this contract changes."""
    if store.get_contract(name) is None:
        raise unknown_name("unknown_contract", name, store.contract_names())
    hashes = store.contract_hashes()
    names = store.dependents_of(name, transitive=transitive)
    return {
        "name": name,
        "transitive": transitive,
        "dependents": [{"name": n, "hash": _short(hashes[n])} for n in names],
    }


def verify(
    root: Path,
    store: Store,
    names: str | list[str],
    python: str | None = None,
    timeout: int | float | None = None,
    pycache_trust: bool = True,
) -> dict:
    """Per-unit cached-pass / pass / fail. Runs pytest only on cache misses."""
    if isinstance(names, str):
        names = [names]
    if not pycache_trust:
        clear_pycache(root)  # once per batch, before any pytest run
    results = []
    for name in names:
        try:
            r = verify_one(root, store, name, python=python, timeout=timeout)
            r.pop("key")  # internal cache key — pure token weight to an agent
            if not r["summary"]:
                r.pop("summary")
            results.append(r)
        except HeddleError as e:
            results.append({"name": name, "status": "error", **e.to_dict()})
    return {"results": results}


def cached_impl_hash(root: Path, store: Store, impl: str, contract: str | None = None) -> str:
    """`impl_hash` memoised by (impl ref, file mtime_ns, size).

    `status` computes an impl hash for every contract; re-reading and re-parsing
    each file on every call is the O(n) cost in ISSUES #10. `verify` never uses
    this — a stale *verification* is unsafe, so it always hashes fresh — but
    `status` is informational, and mtime_ns makes a same-size-same-instant miss
    vanishingly unlikely.
    """
    adapter = adapter_for(impl)
    path = root / impl.partition("::")[0]
    try:
        st = path.stat()
    except OSError:
        return adapter.impl_hash(root, impl, contract=contract)  # absent file: let it raise cleanly
    cached = store.get_cached_impl_hash(impl)
    if cached is not None and cached["mtime_ns"] == st.st_mtime_ns and cached["size"] == st.st_size:
        return cached["impl_hash"]
    h = adapter.impl_hash(root, impl, contract=contract)
    store.put_cached_impl_hash(impl, st.st_mtime_ns, st.st_size, h)
    return h


def status(root: Path, store: Store) -> dict:
    """Dirty contracts, stale verifications, cache hit-rate, token counters."""
    dirty: list[str] = []
    for name in store.contract_names():
        data, _ = _load(store, name)
        if "impl" not in data:
            continue  # spec-only contracts don't need verification
        try:
            ihash = cached_impl_hash(root, store, data["impl"], contract=name)
        except HeddleError:
            dirty.append(name)
            continue
        thash = adapter_for(data["impl"]).test_source_hash(root, data.get("tests", []))
        v = store.get_verification(verification_key(store, name, ihash, thash))
        if v is None or v["status"] != "pass" or v["stale"]:
            dirty.append(name)

    c = store.counters()
    hits, misses = c.get("cache_hits", 0), c.get("cache_misses", 0)
    total = hits + misses
    tokens_by_tool = {k.removeprefix("tokens."): v for k, v in c.items() if k.startswith("tokens.")}
    return {
        "contracts": len(store.contract_names()),
        "dirty": dirty,
        "stale_verifications": store.stale_verifications(),
        "python": resolve_python(root),  # which interpreter verify shells pytest to
        "cache": {
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hits / total, 3) if total else None,
        },
        "tokens": {"total": sum(tokens_by_tool.values()), "by_tool": tokens_by_tool},
    }
