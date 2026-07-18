"""The graphify importer: graph.json in, valid inferred contracts out.

The fixture keeps the graph and the source side by side in this file so the
graph's L<n> locations always agree with the code the test writes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

from hashloom.contract import parse_contract
from hashloom.indexer import index
from hashloom.project import db_path, init_project
from hashloom.store import SqliteStore

# integrations/ is deliberately not a package; load the script by path
_SCRIPT = Path(__file__).resolve().parent.parent / "integrations" / "graphify_import.py"
_spec = importlib.util.spec_from_file_location("graphify_import", _SCRIPT)
gi = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gi  # dataclasses resolves the module at class-creation time
_spec.loader.exec_module(gi)


CALC = """
    from dataclasses import dataclass


    def log_calls(fn):
        return fn


    @dataclass
    class Item:
        value: float
        ok: bool = True


    def total(items: list[Item]) -> float:
        return sum(i.value for i in items if i.ok)


    @log_calls
    def report(items: list[Item]) -> str:
        return f"total: {total(items):.2f}"


    class Ledger:
        def __init__(self, name: str):
            self.name = name

        def add(self, item: Item) -> None:
            self.name += item and ""
"""

OTHER = """
    def total(xs: list[float]) -> float:
        return sum(xs)
"""

TEST_CALC = """
    from src.calc import Item, total, report


    def _make():
        return [Item(2.0)]


    def test_total():
        assert total(_make()) == 2.0


    class TestReport:
        def test_report(self):
            assert report(_make()).startswith("total")
"""


def _line(path: Path, needle: str) -> int:
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not in {path}")


def _node(nid: str, label: str, file: str, line: int | None) -> dict:
    return {
        "id": nid,
        "label": label,
        "file_type": "code",
        "source_file": file,
        "source_location": f"L{line}" if line is not None else None,
    }


def _edge(src: str, tgt: str, relation: str, confidence: str) -> dict:
    return {"source": src, "target": tgt, "relation": relation, "confidence": confidence, "weight": 1.0}


@pytest.fixture
def gproject(tmp_path: Path):
    """Source tree + matching graph.json; returns (root, graph_path)."""
    init_project(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    calc = tmp_path / "src" / "calc.py"
    calc.write_text(textwrap.dedent(CALC).strip() + "\n")
    (tmp_path / "src" / "other.py").write_text(textwrap.dedent(OTHER).strip() + "\n")
    tcalc = tmp_path / "tests" / "test_calc.py"
    tcalc.write_text(textwrap.dedent(TEST_CALC).strip() + "\n")

    graph = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [
            # file-level node: label == basename, L1 — must be ignored
            _node("src_calc", "calc.py", "src/calc.py", 1),
            # class nodes point at the decorator line (tree-sitter style);
            # methods are ".name()" with no class in the label
            _node("src_calc_item", "Item", "src/calc.py", _line(calc, "@dataclass")),
            _node("src_calc_total", "total()", "src/calc.py", _line(calc, "def total")),
            _node("src_calc_report", "report()", "src/calc.py", _line(calc, "@log_calls")),
            _node("src_calc_ledger", "Ledger", "src/calc.py", _line(calc, "class Ledger")),
            _node("src_calc_ledger_add", ".add()", "src/calc.py", _line(calc, "def add")),
            _node("src_other_total", "total()", "src/other.py", 1),
            _node("lib_parse_parse", "parse()", "lib/parse.go", 5),
            _node("tests_test_calc_test_total", "test_total()", "tests/test_calc.py", _line(tcalc, "def test_total")),
            _node("tests_test_calc_test_report", ".test_report()", "tests/test_calc.py", _line(tcalc, "def test_report")),
            _node("tests_test_calc_make", "_make()", "tests/test_calc.py", _line(tcalc, "def _make")),
        ],
        "links": [
            _edge("src_calc_total", "src_calc_item", "calls", "EXTRACTED"),
            _edge("src_calc_report", "src_calc_total", "calls", "EXTRACTED"),
            # never deps: wrong confidence or wrong relation
            _edge("src_calc_report", "src_calc_item", "references", "INFERRED"),
            _edge("src_calc_ledger_add", "src_calc_item", "calls", "AMBIGUOUS"),
            _edge("src_calc_report", "src_calc_item", "imports", "EXTRACTED"),
            # inherits counts as a dep (not source-checked; graph is authority here)
            _edge("src_calc_ledger", "src_calc_item", "inherits", "EXTRACTED"),
            # ranking: gives total a second non-test caller
            _edge("src_calc_ledger_add", "src_calc_total", "calls", "EXTRACTED"),
            # test callers
            _edge("tests_test_calc_test_total", "src_calc_total", "calls", "EXTRACTED"),
            _edge("tests_test_calc_test_report", "src_calc_report", "calls", "EXTRACTED"),
            _edge("tests_test_calc_make", "src_calc_item", "calls", "EXTRACTED"),
        ],
    }
    out = tmp_path / "graphify-out"
    out.mkdir()
    graph_path = out / "graph.json"
    graph_path.write_text(json.dumps(graph))
    return tmp_path, graph_path


def run(root: Path, graph_path: Path, *args: str) -> int:
    return gi.main([str(graph_path), "--root", str(root), *args])


def read_contract(root: Path, name: str) -> dict:
    text = (root / "contracts" / f"{name}.yaml").read_text()
    return parse_contract(text, expect_name=name)


def test_emitted_contract_is_valid_and_inferred(gproject):
    root, graph = gproject
    assert run(root, graph, "--units", "src/calc.py::total", "src/calc.py::Item") == 0
    data = read_contract(root, "total")
    assert data["status"] == "inferred"
    assert data["impl"] == "src/calc.py::total"
    assert data["signature"] == "(items: list[Item]) -> float"


def test_round_trip_through_the_indexer(gproject):
    root, graph = gproject
    assert run(root, graph, "--units", "src/calc.py::total", "src/calc.py::Item") == 0
    store = SqliteStore(db_path(root))
    try:
        index(root, store)
        assert set(store.contract_names()) == {"Item", "total"}
    finally:
        store.close()


def test_deps_only_from_extracted_edges_to_selected_units(gproject):
    root, graph = gproject
    assert run(root, graph, "--units", "src/calc.py::total", "src/calc.py::Item", "src/calc.py::report") == 0
    # report -> total is EXTRACTED calls; report -> Item is only INFERRED/imports
    assert read_contract(root, "report")["deps"] == ["total"]
    # total -> Item EXTRACTED calls survives; edge to non-selected Ledger absent
    assert read_contract(root, "total")["deps"] == ["Item"]
    # dep to a unit outside the selected set is dropped even when EXTRACTED
    assert "deps" not in read_contract(root, "Item")


def test_inferred_and_ambiguous_edges_never_become_deps(gproject):
    root, graph = gproject
    assert run(root, graph, "--units", "src/calc.py::add", "src/calc.py::Item") == 0
    # Ledger.add -> Item is AMBIGUOUS calls: no dep
    assert "deps" not in read_contract(root, "Ledger.add")


def test_inherits_counts_as_a_dep(gproject):
    root, graph = gproject
    assert run(root, graph, "--units", "src/calc.py::Ledger", "src/calc.py::Item") == 0
    assert read_contract(root, "Ledger")["deps"] == ["Item"]


def test_non_python_selected_is_skipped_not_fatal(gproject, capsys):
    root, graph = gproject
    assert run(root, graph, "--units", "src/calc.py::total", "lib/parse.go::parse") == 0
    out = capsys.readouterr().out
    assert "skipped" in out and "lib/parse.go::parse" in out
    assert (root / "contracts" / "total.yaml").exists()
    assert not (root / "contracts" / "parse.yaml").exists()


def test_existing_contract_aborts_everything_unless_forced(gproject, capsys):
    root, graph = gproject
    (root / "contracts" / "total.yaml").write_text("name: total\nsignature: old\n")
    assert run(root, graph, "--units", "src/calc.py::total", "src/calc.py::Item") == 1
    assert "already exists" in capsys.readouterr().err
    # all-or-nothing: the non-colliding unit was not written either
    assert not (root / "contracts" / "Item.yaml").exists()
    assert "signature: old" in (root / "contracts" / "total.yaml").read_text()

    assert run(root, graph, "--units", "src/calc.py::total", "src/calc.py::Item", "--force") == 0
    assert read_contract(root, "total")["signature"] == "(items: list[Item]) -> float"


def test_in_set_name_collision_aborts_naming_both(gproject, capsys):
    root, graph = gproject
    assert run(root, graph, "--units", "src/calc.py::total", "src/other.py::total") == 1
    err = capsys.readouterr().err
    assert "src/calc.py::total" in err and "src/other.py::total" in err
    assert not (root / "contracts" / "total.yaml").exists()


def test_list_ranks_by_non_test_callers(gproject, capsys):
    root, graph = gproject
    assert run(root, graph, "--list") == 0
    lines = capsys.readouterr().out.splitlines()
    order = [line.split()[1] for line in lines]
    # total has 2 non-test callers (report, Ledger.add); Item's only EXTRACTED
    # calls/references callers are total (counts) and a test helper (does not)
    assert order.index("src/calc.py::total") < order.index("src/calc.py::Item")
    assert lines[0].split()[0] == "2"
    # test nodes and file-level nodes are not candidates
    assert not any("tests/test_calc.py" in line for line in lines)
    assert not any("::calc.py" in line for line in lines)


def test_signature_extraction_shapes(gproject):
    root, graph = gproject
    assert (
        run(
            root, graph, "--units",
            "src/calc.py::Item", "src/calc.py::report", "src/calc.py::Ledger", "src/calc.py::add",
        )
        == 0
    )
    # dataclass convention, defaults included; graph pointed at the decorator line
    assert read_contract(root, "Item")["signature"] == "dataclass: Item(value: float, ok: bool = True)"
    # decorated function resolves through the decorator-range match
    assert read_contract(root, "report")["signature"] == "(items: list[Item]) -> str"
    # plain class renders its __init__ args
    assert read_contract(root, "Ledger")["signature"] == "class: Ledger(name: str)"
    # method drops self, keeps the dotted contract name
    assert read_contract(root, "Ledger.add")["signature"] == "(item: Item) -> None"
    assert read_contract(root, "Ledger.add")["impl"] == "src/calc.py::Ledger.add"


def test_stale_line_falls_back_to_name_then_skips(gproject, capsys):
    root, graph_path = gproject
    graph = json.loads(graph_path.read_text())
    for n in graph["nodes"]:
        if n["id"] == "src_calc_total":
            n["source_location"] = "L999"
    graph_path.write_text(json.dumps(graph))
    assert run(root, graph_path, "--units", "src/calc.py::total") == 0
    assert "resolved 'total' by name" in capsys.readouterr().err
    assert (root / "contracts" / "total.yaml").exists()

    for n in graph["nodes"]:
        if n["id"] == "src_calc_total":
            n["label"] = "ghost()"
    graph_path.write_text(json.dumps(graph))
    assert run(root, graph_path, "--units", "src/calc.py::ghost", "--force") == 1
    assert "skipped" in capsys.readouterr().out


def test_test_candidates_including_class_based(gproject):
    root, graph = gproject
    assert run(root, graph, "--units", "src/calc.py::total", "src/calc.py::report", "src/calc.py::Item") == 0
    assert read_contract(root, "total")["tests"] == ["tests/test_calc.py::test_total"]
    assert read_contract(root, "report")["tests"] == ["tests/test_calc.py::TestReport::test_report"]
    # _make calls Item from tests/ but is a helper, not a collectible test
    assert "tests" not in read_contract(root, "Item")


def test_bare_name_selector_ambiguity(gproject, capsys):
    root, graph = gproject
    assert run(root, graph, "--units", "total") == 1
    err = capsys.readouterr().err
    assert "ambiguous" in err and "src/other.py::total" in err
    # unambiguous bare name works
    assert run(root, graph, "--units", "report") == 0
    assert (root / "contracts" / "report.yaml").exists()


def test_dry_run_writes_nothing(gproject, capsys):
    root, graph = gproject
    assert run(root, graph, "--units", "src/calc.py::total", "--dry-run") == 0
    assert "would emit" in capsys.readouterr().out
    assert not (root / "contracts" / "total.yaml").exists()


def test_rejects_a_non_graph_json(gproject, tmp_path):
    root, _ = gproject
    bogus = tmp_path / "not_a_graph.json"
    bogus.write_text('{"foo": 1}')
    with pytest.raises(SystemExit):
        gi.main([str(bogus), "--root", str(root), "--list"])


def test_accepts_edges_key_alias(gproject):
    # the v8 build step renames NetworkX's "links" to "edges"; both must load
    root, graph_path = gproject
    graph = json.loads(graph_path.read_text())
    graph["edges"] = graph.pop("links")
    graph_path.write_text(json.dumps(graph))
    assert run(root, graph_path, "--units", "src/calc.py::total") == 0
    assert "deps" not in read_contract(root, "total")  # Item not selected
