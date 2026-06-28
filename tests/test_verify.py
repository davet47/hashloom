"""Verification cache: pytest runs only on cache misses; contract or impl
changes anywhere in the dep closure bust the cache; failure summaries stay
within the token budget."""

from heddle import api, tokens
from heddle.indexer import index
from heddle.verify import SUMMARY_MAX_TOKENS

from .conftest import write_contract


def statuses(out):
    return {r["name"]: r["status"] for r in out["results"]}


def test_first_run_passes_then_caches(project):
    root, store = project
    assert statuses(api.verify(root, store, ["total", "report"])) == {"total": "pass", "report": "pass"}
    assert statuses(api.verify(root, store, ["total", "report"])) == {
        "total": "cached-pass",
        "report": "cached-pass",
    }
    c = store.counters()
    assert c["cache_hits"] == 2 and c["test_runs"] == 2


def test_impl_change_busts_cache_for_that_unit_only(project):
    root, store = project
    api.verify(root, store, ["total", "report"])
    calc = root / "src" / "calc.py"
    # behaviour-preserving rewrite of report; total untouched
    calc.write_text(calc.read_text().replace(
        'return f"total: {total(items):.2f}"',
        'amount = total(items)\n    return f"total: {amount:.2f}"',
    ))
    assert statuses(api.verify(root, store, ["total", "report"])) == {
        "total": "cached-pass",
        "report": "pass",
    }


def test_formatting_only_impl_change_stays_cached(project):
    root, store = project
    api.verify(root, store, ["total"])
    calc = root / "src" / "calc.py"
    calc.write_text(calc.read_text().replace(
        "return sum(i.value for i in items if i.ok)",
        "# comment added, formatting shuffled\n    return sum(\n        i.value for i in items if i.ok\n    )",
    ))
    assert statuses(api.verify(root, store, ["total"])) == {"total": "cached-pass"}


def test_test_source_change_busts_cache_for_that_unit_only(project):
    root, store = project
    api.verify(root, store, ["total", "report"])
    tfile = root / "tests" / "test_calc.py"
    # change test_total's body (a stricter assertion); test_report untouched
    tfile.write_text(tfile.read_text().replace(
        "assert total([Item(2.0, True), Item(3.0, False)]) == 2.0",
        "assert total([Item(2.0, True), Item(3.0, False)]) == 2.0\n    assert total([]) == 0.0",
    ))
    assert statuses(api.verify(root, store, ["total", "report"])) == {
        "total": "pass",            # its own test source changed -> re-run
        "report": "cached-pass",
    }


def test_formatting_only_test_change_stays_cached(project):
    root, store = project
    api.verify(root, store, ["total"])
    tfile = root / "tests" / "test_calc.py"
    # add a comment and reflow inside test_total; behaviour identical
    tfile.write_text(tfile.read_text().replace(
        "def test_total():\n    assert total([Item(2.0, True), Item(3.0, False)]) == 2.0",
        "def test_total():\n    # reformatted, same assertion\n    assert total(\n        [Item(2.0, True), Item(3.0, False)]\n    ) == 2.0",
    ))
    assert statuses(api.verify(root, store, ["total"])) == {"total": "cached-pass"}


def test_dep_contract_change_busts_dependent_cache(project):
    root, store = project
    api.verify(root, store, ["total", "report"])
    write_contract(root, "Item", """
        name: Item
        signature: "dataclass: value: float, ok: bool, tag: str"
        invariants:
          - value may be any float
    """)
    index(root, store)
    # Item's signature changed: both dependents re-run even though their own yaml/impl didn't move
    assert statuses(api.verify(root, store, ["total", "report"])) == {"total": "pass", "report": "pass"}


def test_failure_summary_is_short_and_useful(project):
    root, store = project
    calc = root / "src" / "calc.py"
    calc.write_text(calc.read_text().replace("if i.ok", "if True"))
    out = api.verify(root, store, ["total"])
    result = out["results"][0]
    assert result["status"] == "fail"
    assert "test_total" in result["summary"]
    assert tokens.count(result["summary"]) <= SUMMARY_MAX_TOKENS
    assert "Traceback" not in result["summary"]


def test_failures_are_not_served_from_cache(project):
    root, store = project
    calc = root / "src" / "calc.py"
    good = calc.read_text()
    calc.write_text(good.replace("if i.ok", "if True"))
    assert statuses(api.verify(root, store, ["total"])) == {"total": "fail"}
    assert statuses(api.verify(root, store, ["total"])) == {"total": "fail"}  # re-runs, no cached-fail
    calc.write_text(good)
    assert statuses(api.verify(root, store, ["total"])) == {"total": "pass"}


def test_verify_spec_only_contract_errors_cleanly(project):
    root, store = project
    out = api.verify(root, store, ["Item", "missing_one"])
    by_name = {r["name"]: r for r in out["results"]}
    assert by_name["Item"]["status"] == "error"
    assert by_name["Item"]["error"]["code"] == "no_impl"
    assert by_name["missing_one"]["error"]["code"] == "unknown_contract"


def test_status_reports_dirty_and_hit_rate(project):
    root, store = project
    s = api.status(root, store)
    assert set(s["dirty"]) == {"total", "report"}  # indexed but never verified
    api.verify(root, store, ["total", "report"])
    api.verify(root, store, ["total"])
    s = api.status(root, store)
    assert s["dirty"] == []
    assert s["cache"]["hits"] == 1 and s["cache"]["misses"] == 2
    assert s["contracts"] == 3


def test_status_reports_wasted_rechecks(project):
    root, store = project
    api.verify(root, store, ["total", "report"])  # both green
    # change Item's contract signature: busts total/report keys (Item's hash is in
    # them) but the real code is unchanged, so both still pass -> wasted rechecks
    write_contract(root, "Item", """
        name: Item
        signature: "dataclass: value: float, ok: bool, extra: int"
        invariants:
          - value may be any float
    """)
    index(root, store)
    assert statuses(api.verify(root, store, ["total", "report"])) == {"total": "pass", "report": "pass"}
    rc = api.status(root, store)["rechecks"]
    assert rc["after_change"] == 2
    assert rc["verdict_unchanged"] == 2
    assert rc["wasted_rate"] == 1.0
