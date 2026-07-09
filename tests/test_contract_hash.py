"""Hash stability — the load-bearing tests. Formatting changes must not change
hashes; meaning changes must."""

import pytest

from hashloom.contract import contract_hash, parse_contract
from hashloom.errors import HashloomError

BASE = """
name: revenue_by_region
signature: "(sales: list[Sale]) -> dict[Region, float]"
deps: [Sale, Region]
invariants:
  - excludes sales where completed is false
  - excludes sales with null amount
examples:
  - in:  "[Sale(r='QLD', amt=10)]"
    out: "{'QLD': 10.0}"
tests: [tests/test_revenue.py::test_revenue_by_region]
impl: src/revenue.py::revenue_by_region
"""


def h(text: str) -> str:
    return contract_hash(parse_contract(text))


def test_identical_text_same_hash():
    assert h(BASE) == h(BASE)


def test_comments_do_not_change_hash():
    commented = BASE.replace("deps: [Sale, Region]", "deps: [Sale, Region]  # the warp threads")
    assert h(commented) == h(BASE)


def test_key_order_does_not_change_hash():
    reordered = """
impl: src/revenue.py::revenue_by_region
signature: "(sales: list[Sale]) -> dict[Region, float]"
name: revenue_by_region
deps: [Sale, Region]
tests: [tests/test_revenue.py::test_revenue_by_region]
examples:
  - in:  "[Sale(r='QLD', amt=10)]"
    out: "{'QLD': 10.0}"
invariants:
  - excludes sales where completed is false
  - excludes sales with null amount
"""
    assert h(reordered) == h(BASE)


def test_whitespace_does_not_change_hash():
    spaced = BASE.replace("excludes sales where completed is false", "excludes  sales   where completed is false ")
    assert h(spaced) == h(BASE)


def test_yaml_style_does_not_change_hash():
    block_style = BASE.replace("deps: [Sale, Region]", "deps:\n  - Sale\n  - Region")
    assert h(block_style) == h(BASE)


def test_deps_order_does_not_change_hash():
    swapped = BASE.replace("deps: [Sale, Region]", "deps: [Region, Sale]")
    assert h(swapped) == h(BASE)


def test_impl_and_tests_paths_do_not_change_hash():
    relocated = BASE.replace("src/revenue.py", "src/moved/revenue.py").replace(
        "tests/test_revenue.py", "tests/unit/test_revenue.py"
    )
    assert h(relocated) == h(BASE)


def test_invariant_order_does_not_change_hash():
    # #19: invariants are excluded from the hash, so reordering them is cosmetic
    swapped = BASE.replace(
        "  - excludes sales where completed is false\n  - excludes sales with null amount",
        "  - excludes sales with null amount\n  - excludes sales where completed is false",
    )
    assert h(swapped) == h(BASE)


def test_status_does_not_change_hash():
    # status is provenance, not meaning: adding it or flipping it never
    # invalidates — confirming an inferred contract must be free
    assert h(BASE + "status: inferred\n") == h(BASE)
    assert h(BASE + "status: confirmed\n") == h(BASE)


def test_invalid_status_rejected():
    with pytest.raises(HashloomError) as exc:
        parse_contract(BASE + "status: draft\n")
    assert exc.value.code == "invalid_shape"


def test_signature_change_changes_hash():
    changed = BASE.replace("dict[Region, float]", "dict[Region, int]")
    assert h(changed) != h(BASE)


def test_invariant_wording_does_not_change_hash():
    # #19: rewording an invariant no longer busts the hash (it is documentation)
    changed = BASE.replace("null amount", "missing amount")
    assert h(changed) == h(BASE)


def test_example_change_changes_hash():
    changed = BASE.replace("{'QLD': 10.0}", "{'QLD': 11.0}")
    assert h(changed) != h(BASE)


def test_unknown_key_rejected():
    with pytest.raises(HashloomError) as exc:
        parse_contract(BASE + "\nnotes: extra\n")
    assert exc.value.code == "invalid_shape"


def test_missing_signature_rejected():
    with pytest.raises(HashloomError) as exc:
        parse_contract("name: thing\n")
    assert exc.value.code == "invalid_shape"


def test_bad_yaml_rejected():
    with pytest.raises(HashloomError) as exc:
        parse_contract("name: [unclosed")
    assert exc.value.code == "invalid_yaml"


def test_name_mismatch_rejected():
    with pytest.raises(HashloomError) as exc:
        parse_contract(BASE, expect_name="something_else")
    assert exc.value.code == "name_mismatch"
