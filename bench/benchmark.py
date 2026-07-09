"""Side-by-side token benchmark: the launch demo.

Simulates the same three regeneration tasks against examples/sales, twice:

  raw mode    — what an agent on plain files reads per task: the unit's spec
                file, every transitive dep's spec file, every source module in
                the dep closure, and the full pytest output of the whole suite.
  hashloom mode — the get_contract packet, a blast-radius check, and the verify
                response (pytest runs server-side; the agent never reads it).

Both modes count tokens with the same tiktoken encoder. Run:

    uv run python bench/benchmark.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from hashloom import api, tokens  # noqa: E402
from hashloom.indexer import index  # noqa: E402
from hashloom.project import db_path, init_project  # noqa: E402
from hashloom.store import Store, SqliteStore  # noqa: E402

SALES = REPO / "examples" / "sales"
# one regeneration task per layer of the dependency graph
TASKS = ["revenue_by_region", "top_customers", "revenue_by_category"]


def fresh_store() -> Store:
    shutil.rmtree(SALES / ".hashloom", ignore_errors=True)
    init_project(SALES)
    store = SqliteStore(db_path(SALES))
    index(SALES, store)
    return store


def raw_task_tokens(store: Store, name: str) -> int:
    """Tokens an agent reads to regenerate `name` from plain files."""
    import yaml

    closure = [name, *store.transitive_deps(name)]
    spec_text = "".join((SALES / "contracts" / f"{n}.yaml").read_text() for n in closure)

    src_files, test_files = set(), set()
    for n in closure:
        data = yaml.safe_load(store.get_contract(n)["yaml"])
        if "impl" in data:
            src_files.add(data["impl"].partition("::")[0])
        if n == name:  # the full relevant test surface for the unit being rewoven
            test_files.update(t.partition("::")[0] for t in data.get("tests", []))
    src_text = "".join((SALES / f).read_text() for f in sorted(src_files | test_files))

    # default verbosity: that is what lands in an agent's context when it runs
    # the suite itself (hashloom runs -q server-side and serves a summary instead)
    pytest_out = subprocess.run(
        [sys.executable, "-B", "-m", "pytest"],
        cwd=SALES, capture_output=True, text=True,
    ).stdout

    return tokens.count(spec_text) + tokens.count(src_text) + tokens.count(pytest_out)


def hashloom_task_tokens(store: Store, name: str) -> int:
    """Tokens an agent reads to regenerate `name` through the MCP tools."""
    responses = [
        api.get_contract(SALES, store, name),
        api.get_dependents(SALES, store, name, transitive=True),
        api.verify(SALES, store, [name]),
    ]
    return sum(tokens.count(json.dumps(r, ensure_ascii=False)) for r in responses)


def main() -> None:
    store = fresh_store()
    raw = {t: raw_task_tokens(store, t) for t in TASKS}

    store = fresh_store()
    # warm cache the way a real project would be: everything verified green once
    api.verify(SALES, store, [t for t in store.contract_names() if t != "Region"])
    store.reset_counters()
    hashloom = {t: hashloom_task_tokens(store, t) for t in TASKS}
    cache = api.status(SALES, store)["cache"]

    width = max(map(len, TASKS))
    print(f"\n{'task':<{width}}  {'raw files':>10}  {'hashloom':>10}  {'reduction':>10}")
    print("-" * (width + 38))
    for t in TASKS:
        print(f"{t:<{width}}  {raw[t]:>10,}  {hashloom[t]:>10,}  {raw[t] / hashloom[t]:>9.1f}x")
    total_raw, total_hashloom = sum(raw.values()), sum(hashloom.values())
    print("-" * (width + 38))
    print(f"{'total':<{width}}  {total_raw:>10,}  {total_hashloom:>10,}  {total_raw / total_hashloom:>9.1f}x")
    print(f"\nverification cache during hashloom run: {cache['hits']} hits / {cache['misses']} misses\n")

    if total_raw / total_hashloom < 5:
        sys.exit("FAIL: below the 5x definition-of-done line")


if __name__ == "__main__":
    main()
