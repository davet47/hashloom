from __future__ import annotations

import textwrap

from heddle import api
from heddle.contract import diff_contracts


def _c(**kw) -> dict:
    """A minimal parsed contract with the required fields, plus overrides."""
    base = {"name": "x", "signature": "() -> None"}
    base.update(kw)
    return base


# --- unit: diff_contracts is a pure function over parsed contracts ---


def test_signature_change():
    d = diff_contracts(_c(signature="(a) -> int"), _c(signature="(a) -> str"))
    assert d == {"signature": {"old": "(a) -> int", "new": "(a) -> str"}}


def test_deps_added_removed_but_reorder_is_not_meaning():
    assert diff_contracts(_c(deps=["A", "B"]), _c(deps=["B", "C"])) == {
        "deps": {"added": ["C"], "removed": ["A"]}
    }
    # deps carry no order meaning (the hash sorts them), so a reorder is no change
    assert diff_contracts(_c(deps=["A", "B"]), _c(deps=["B", "A"])) == {}


def test_invariants_add_remove_reorder():
    assert diff_contracts(_c(invariants=["a"]), _c(invariants=["a", "b"])) == {
        "invariants": {"added": ["b"]}
    }
    assert diff_contracts(_c(invariants=["a", "b"]), _c(invariants=["a"])) == {
        "invariants": {"removed": ["b"]}
    }
    # invariant order IS meaning (the hash preserves it), so a reorder is a change
    assert diff_contracts(_c(invariants=["a", "b"]), _c(invariants=["b", "a"])) == {
        "invariants": {"reordered": True}
    }


def test_examples_add_and_reorder():
    e1, e2 = {"in": "1", "out": "2"}, {"in": "3", "out": "4"}
    assert diff_contracts(_c(examples=[e1]), _c(examples=[e1, e2])) == {
        "examples": {"added": [e2]}
    }
    assert diff_contracts(_c(examples=[e1, e2]), _c(examples=[e2, e1])) == {
        "examples": {"reordered": True}
    }


def test_impl_and_tests_reported_though_excluded_from_hash():
    assert diff_contracts(_c(impl="a.py::f"), _c(impl="b.py::f")) == {
        "impl": {"old": "a.py::f", "new": "b.py::f"}
    }
    assert diff_contracts(_c(tests=["t.py::a"]), _c(tests=["t.py::a", "t.py::b"])) == {
        "tests": {"old": ["t.py::a"], "new": ["t.py::a", "t.py::b"]}
    }


def test_cosmetic_only_edit_is_empty():
    # whitespace is normalised away, exactly as the hash does
    assert (
        diff_contracts(
            _c(signature="() -> None", invariants=["a  b"]),
            _c(signature="()  ->  None", invariants=[" a b "]),
        )
        == {}
    )


# --- integration: put_contract surfaces the diff ---


def test_put_contract_includes_diff(project):
    root, store = project
    new_yaml = textwrap.dedent("""
        name: total
        signature: "(items: list[Item]) -> int"
        deps: [Item]
        invariants:
          - excludes items where ok is false
          - returns zero for an empty list
        tests: [tests/test_calc.py::test_total]
        impl: src/calc.py::total
    """).strip() + "\n"
    out = api.put_contract(root, store, "total", new_yaml)
    assert out["changed"] is True
    assert out["diff"]["signature"] == {
        "old": "(items: list[Item]) -> float",
        "new": "(items: list[Item]) -> int",
    }
    assert out["diff"]["invariants"] == {"added": ["returns zero for an empty list"]}


def test_put_contract_cosmetic_edit_has_no_diff(project):
    root, store = project
    text = (root / "contracts" / "total.yaml").read_text()
    out = api.put_contract(root, store, "total", text + "\n# trailing comment\n")
    assert out["changed"] is False
    assert "diff" not in out


def test_put_contract_new_contract_has_no_diff(project):
    root, store = project
    out = api.put_contract(root, store, "thing", 'name: thing\nsignature: "() -> None"\n')
    assert out["changed"] is True
    assert "diff" not in out
