"""The shared verification cache: one client's green is served to another
without re-running pytest, and impl blobs write through to the shared store."""

from __future__ import annotations

import textwrap
from pathlib import Path

from hashloom import api
from hashloom.indexer import index
from hashloom.project import init_project
from hashloom.shared import LayeredStore
from hashloom.store import SqliteStore


def _make_project(root: Path) -> None:
    init_project(root)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "__init__.py").write_text("")
    (root / "tests" / "__init__.py").write_text("")
    (root / "contracts" / "total.yaml").write_text(textwrap.dedent("""
        name: total
        signature: "(xs: list[int]) -> int"
        tests: [tests/test_x.py::test_total]
        impl: src/x.py::total
    """).strip() + "\n")
    (root / "src" / "x.py").write_text("def total(xs):\n    return sum(xs)\n")
    (root / "tests" / "test_x.py").write_text(
        "from src.x import total\n\n\ndef test_total():\n    assert total([1, 2]) == 3\n"
    )


def test_shared_green_is_served_to_a_second_client(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _make_project(root)
    shared = SqliteStore(tmp_path / "shared.db")

    # client A: local + shared. verify runs pytest once and publishes the green.
    a_local = SqliteStore(root / ".hashloom" / "a.db")
    a = LayeredStore(a_local, shared)
    index(root, a)
    assert api.verify(root, a, ["total"])["results"][0]["status"] == "pass"
    assert a_local.counters().get("test_runs", 0) == 1

    # blobs wrote through to the shared store (serve weft, not only verdicts)
    blob_hash = a_local.get_impl("total")["blob_hash"]
    assert shared.get_blob(blob_hash) is not None

    # client B: fresh local, same shared. the green is served WITHOUT pytest.
    b_local = SqliteStore(root / ".hashloom" / "b.db")
    b = LayeredStore(b_local, shared)
    index(root, b)
    assert api.verify(root, b, ["total"])["results"][0]["status"] == "cached-pass"
    assert b_local.counters().get("test_runs", 0) == 0  # B never ran pytest

    shared.close()
    a_local.close()
    b_local.close()


def test_failures_are_not_published_to_the_shared_store(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _make_project(root)
    # break the impl so the test fails
    (root / "src" / "x.py").write_text("def total(xs):\n    return 0\n")
    shared = SqliteStore(tmp_path / "shared.db")
    a = LayeredStore(SqliteStore(root / ".hashloom" / "a.db"), shared)
    index(root, a)
    assert api.verify(root, a, ["total"])["results"][0]["status"] == "fail"

    # a second client must NOT see a cached pass; failures never cross the boundary
    b_local = SqliteStore(root / ".hashloom" / "b.db")
    b = LayeredStore(b_local, shared)
    index(root, b)
    assert api.verify(root, b, ["total"])["results"][0]["status"] == "fail"  # re-runs, no shared green
    shared.close()
