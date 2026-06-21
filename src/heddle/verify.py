"""Hash-keyed verification: run pytest only on cache misses.

Verification key = sha256 over (contract_hash, impl_hash, transitive dep
contract hashes). A cached green result is valid iff the full key matches —
any contract edit anywhere in the dependency closure produces a new key.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from . import tokens
from .config import resolve_python, resolve_timeout
from .errors import HeddleError, unknown_name
from .implhash import impl_hash
from .store import Store

SUMMARY_MAX_TOKENS = 40

# directories whose bytecode is not the project's regenerable weft — never nuked
_PYCACHE_SKIP = frozenset({".venv", "venv", ".heddle", "site-packages", ".git", ".tox", "node_modules"})


def clear_pycache(root: Path) -> int:
    """Remove project __pycache__ dirs so a verify run can't load stale bytecode.

    Prunes virtualenvs, the store, and VCS/vendor dirs from the walk — only the
    project's own regenerable bytecode is cleared, and a big .venv is never
    traversed. Returns the number of dirs removed.
    """
    removed = 0
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _PYCACHE_SKIP]  # don't descend into them
        if "__pycache__" in dirnames:
            pc = Path(dirpath) / "__pycache__"
            if pc.is_symlink():
                pc.unlink()  # detach the link so its stale cache can't be loaded; leave the target
            else:
                shutil.rmtree(pc, ignore_errors=True)
            dirnames.remove("__pycache__")  # already gone; don't descend
            removed += 1
    return removed


def verification_key(store: Store, name: str, ihash: str) -> str:
    row = store.get_contract(name)
    if row is None:
        raise unknown_name("unknown_contract", name, store.contract_names())
    chash = row["hash"]
    hashes = store.contract_hashes()
    dep_part = ",".join(f"{d}={hashes[d]}" for d in store.transitive_deps(name) if d in hashes)
    raw = f"contract={chash}|impl={ihash}|deps={dep_part}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _failure_summary(stdout: str) -> str:
    """Assertion line + values, never a full traceback. ≤ ~40 tokens."""
    lines = stdout.splitlines()
    failed = next((l.strip() for l in lines if l.startswith("FAILED ")), "")
    # pytest prefixes assertion/error detail lines with 'E '
    detail = [l.strip()[2:].strip() for l in lines if l.strip().startswith("E ")]
    parts = []
    if failed:
        parts.append(failed.split(" - ")[0].removeprefix("FAILED "))
    parts.extend(detail[:3])
    summary = " | ".join(p for p in parts if p) or "tests failed (no assertion detail captured)"
    return tokens.truncate(re.sub(r"\s+", " ", summary), SUMMARY_MAX_TOKENS)


def _run_pytest(root: Path, node_ids: list[str], python: str, timeout: int | float) -> tuple[bool, str]:
    proc = subprocess.run(
        # -B: regeneration loops rewrite source faster than mtime granularity,
        # so cached bytecode could silently test the previous weft
        [python, "-B", "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", *node_ids],
        cwd=root,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = proc.stdout + "\n" + proc.stderr
    if proc.returncode in (2, 3, 4):  # interrupted / internal error / usage error
        raise HeddleError(
            "tests_failed_to_run",
            tokens.truncate("pytest could not run: " + re.sub(r"\s+", " ", out.strip()), 60),
        )
    # shelling out to a target venv that lacks pytest reports as exit 1 ("No
    # module named pytest"); surface that as a runner error, not a test failure
    if proc.returncode == 1 and "No module named pytest" in out:
        raise HeddleError("tests_failed_to_run", f"pytest is not installed in '{python}'")
    return proc.returncode == 0, out


def verify_one(
    root: Path, store: Store, name: str, python: str | None = None, timeout: int | float | None = None
) -> dict:
    """Verify a single contract. Returns {name, status, summary, key}.

    `python` is the interpreter to run pytest with and `timeout` its per-run
    budget; both resolve lazily from the project when None, so direct callers
    (CLI, benchmark, tests) need not pass them.
    """
    interp = python or resolve_python(root)
    budget = timeout if timeout is not None else resolve_timeout(root)
    row = store.get_contract(name)
    if row is None:
        raise unknown_name("unknown_contract", name, store.contract_names())
    data = yaml.safe_load(row["yaml"])

    if "impl" not in data:
        raise HeddleError("no_impl", f"'{name}' is spec-only (no impl) — nothing to verify", contract=name)
    if not data.get("tests"):
        raise HeddleError("no_tests", f"'{name}' has an impl but no tests — add pytest node IDs", contract=name)

    ihash = impl_hash(root, data["impl"], contract=name)  # always fresh from disk
    store.upsert_impl(name, ihash, data["impl"].partition("::")[0])
    key = verification_key(store, name, ihash)

    store.incr("verify_requests")
    cached = store.get_verification(key)
    if cached is not None and cached["status"] == "pass" and not cached["stale"]:
        store.incr("cache_hits")
        return {"name": name, "status": "cached-pass", "summary": cached["summary"], "key": key}

    store.incr("cache_misses")
    store.incr("test_runs")
    ok, out = _run_pytest(root, data["tests"], interp, budget)
    if ok:
        summary = ""
        store.record_verification(key, name, "pass", summary)
        return {"name": name, "status": "pass", "summary": summary, "key": key}

    summary = _failure_summary(out)
    store.record_verification(key, name, "fail", summary)
    return {"name": name, "status": "fail", "summary": summary, "key": key}
