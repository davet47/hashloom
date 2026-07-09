"""Full-sweep token benchmark for any hashloom project: raw files vs hashloom.

The same methodology as bench/benchmark.py, generalized: sweep every contract
that has an impl and tests, regenerating each once, and compare what an agent
reads in raw mode (the unit's and every transitive dep's spec + source, the
unit's tests, and one full test-suite run's output) against hashloom mode (the
get_contract packet, a blast-radius check, and the verify response).

Language-aware only where it must be: the suite-output component runs each
project's natural runner (pytest / `go test ./...` / `node --test` / `mvn -q
test`), chosen by the impl extensions present. No pass/fail gate — bench/benchmark.py remains
the DoD guard; this reports.

    uv run python bench/sweep.py examples/sales
    uv run python bench/sweep.py examples/go-ledger
    uv run python bench/sweep.py examples/ts-cart       # npm install there first
    uv run python bench/sweep.py examples/java-payroll  # needs a JDK + Maven
"""

from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from hashloom import api, tokens  # noqa: E402
from hashloom.indexer import index  # noqa: E402
from hashloom.project import db_path, init_project  # noqa: E402
from hashloom.store import Store, SqliteStore  # noqa: E402

SUITE_CMDS = {
    ".py": [sys.executable, "-B", "-m", "pytest"],
    ".go": ["go", "test", "./..."],
    ".ts": ["node", "--test", "--experimental-strip-types"],
    ".java": ["mvn", "--batch-mode", "-q", "test"],
}


def fresh_store(root: Path) -> Store:
    shutil.rmtree(root / ".hashloom", ignore_errors=True)
    init_project(root)
    store = SqliteStore(db_path(root))
    index(root, store)
    return store


def sweepable(store: Store) -> list[str]:
    """Contracts with an impl and tests — the units a regeneration would verify."""
    out = []
    for name in store.contract_names():
        data = yaml.safe_load(store.get_contract(name)["yaml"])
        if "impl" in data and data.get("tests"):
            out.append(name)
    return out


def suite_output_tokens(root: Path, names: list[str], store: Store) -> int:
    """One full-suite run per language present, at each runner's defaults —
    except Maven, run with -q: its INFO log would swamp the comparison, so a
    green Java suite contributes zero tokens (the most conservative baseline).
    """
    exts = set()
    for name in names:
        data = yaml.safe_load(store.get_contract(name)["yaml"])
        ext = Path(data["impl"].partition("::")[0]).suffix
        exts.add(".ts" if ext in (".tsx", ".mts", ".cts") else ext)
    total = 0
    for ext in sorted(exts):
        proc = subprocess.run(SUITE_CMDS[ext], cwd=root, capture_output=True, text=True)
        total += tokens.count(proc.stdout + proc.stderr)
    return total


def raw_task_tokens(root: Path, store: Store, name: str, suite_tokens: int) -> int:
    """Tokens an agent reads to regenerate `name` from plain files."""
    closure = [name, *store.transitive_deps(name)]
    spec_text = "".join((root / "contracts" / f"{n}.yaml").read_text() for n in closure)
    src_files, test_files = set(), set()
    for n in closure:
        data = yaml.safe_load(store.get_contract(n)["yaml"])
        if "impl" in data:
            src_files.add(data["impl"].partition("::")[0])
        if n == name:
            test_files.update(t.partition("::")[0] for t in data.get("tests", []))
    src_text = "".join((root / f).read_text() for f in sorted(src_files | test_files))
    return tokens.count(spec_text) + tokens.count(src_text) + suite_tokens


def hashloom_task_tokens(root: Path, store: Store, name: str) -> int:
    """Tokens an agent reads to regenerate `name` through the MCP tools."""
    responses = [
        api.get_contract(root, store, name),
        api.get_dependents(root, store, name, transitive=True),
        api.verify(root, store, [name]),
    ]
    return sum(tokens.count(json.dumps(r, ensure_ascii=False)) for r in responses)


def main() -> None:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    store = fresh_store(root)
    names = sweepable(store)
    skipped = len(store.contract_names()) - len(names)

    # warm the cache the way a real project would be: everything verified green
    # once, so hashloom-mode verify responses are the cached-pass size
    api.verify(root, store, names)
    suite_tokens = suite_output_tokens(root, names, store)

    rows = []
    for name in names:
        raw = raw_task_tokens(root, store, name, suite_tokens)
        via = hashloom_task_tokens(root, store, name)
        rows.append((name, raw, via, raw / via))
    rows.sort(key=lambda r: -r[3])

    width = max(len(r[0]) for r in rows)
    print(f"\nsuite output read per raw regeneration: {suite_tokens} tokens")
    print(f"\n{'unit':<{width}}  {'raw files':>10}  {'hashloom':>10}  {'reduction':>10}")
    print("-" * (width + 38))
    for name, raw, via, ratio in rows:
        print(f"{name:<{width}}  {raw:>10,}  {via:>10,}  {ratio:>9.1f}x")
    total_raw = sum(r[1] for r in rows)
    total_via = sum(r[2] for r in rows)
    print("-" * (width + 38))
    print(f"{'ALL ' + str(len(rows)) + ' units':<{width}}  {total_raw:>10,}  {total_via:>10,}  {total_raw / total_via:>9.1f}x")
    print(f"median per-unit: {statistics.median(r[3] for r in rows):.1f}x", end="")
    print(f"  (skipped {skipped} spec-only/testless contracts)" if skipped else "")


if __name__ == "__main__":
    main()
