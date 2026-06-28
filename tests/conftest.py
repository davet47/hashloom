from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from heddle.indexer import index
from heddle.project import db_path, init_project
from heddle.store import SqliteStore


@pytest.fixture
def project(tmp_path: Path):
    """A tiny indexed project: Item (type) <- total <- report, with impls and tests."""
    init_project(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "tests" / "__init__.py").write_text("")

    write_contract(tmp_path, "Item", """
        name: Item
        signature: "dataclass: value: float, ok: bool"
        invariants:
          - value may be any float
    """)
    write_contract(tmp_path, "total", """
        name: total
        signature: "(items: list[Item]) -> float"
        deps: [Item]
        invariants:
          - excludes items where ok is false
        tests: [tests/test_calc.py::test_total]
        impl: src/calc.py::total
    """)
    write_contract(tmp_path, "report", """
        name: report
        signature: "(items: list[Item]) -> str"
        deps: [Item, total]
        invariants:
          - renders the total to two decimal places
        tests: [tests/test_calc.py::test_report]
        impl: src/calc.py::report
    """)

    (tmp_path / "src" / "calc.py").write_text(textwrap.dedent("""
        from dataclasses import dataclass


        @dataclass
        class Item:
            value: float
            ok: bool


        def total(items):
            return sum(i.value for i in items if i.ok)


        def report(items):
            return f"total: {total(items):.2f}"
    """))
    (tmp_path / "tests" / "test_calc.py").write_text(textwrap.dedent("""
        from src.calc import Item, total, report


        def test_total():
            assert total([Item(2.0, True), Item(3.0, False)]) == 2.0


        def test_report():
            assert report([Item(2.0, True)]) == "total: 2.00"
    """))

    store = SqliteStore(db_path(tmp_path))
    index(tmp_path, store)
    yield tmp_path, store
    store.close()


def write_contract(root: Path, name: str, body: str) -> None:
    (root / "contracts" / f"{name}.yaml").write_text(textwrap.dedent(body).strip() + "\n")
