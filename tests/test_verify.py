"""Verification cache: pytest runs only on cache misses; contract or impl
changes anywhere in the dep closure bust the cache; failure summaries stay
within the token budget."""

from hashloom import api, tokens
from hashloom.indexer import index
from hashloom.verify import SUMMARY_MAX_TOKENS

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


def test_ok_bit_is_the_gate(project):
    root, store = project
    assert api.verify(root, store, ["total", "report"])["ok"] is True
    calc = root / "src" / "calc.py"
    calc.write_text(calc.read_text().replace("if i.ok", "if True"))
    assert api.verify(root, store, ["total", "report"])["ok"] is False
    # an error (spec-only, unknown name) blocks the gate too — unverifiable != verified
    assert api.verify(root, store, ["Item"])["ok"] is False
    assert api.verify(root, store, ["nope"])["ok"] is False


def test_radius_verifies_the_blast_radius_in_one_call(project):
    root, store = project
    # Item is spec-only: it drops out of the expansion, its dependents gate
    out = api.verify(root, store, ["Item"], radius=True)
    assert {r["name"] for r in out["results"]} == {"total", "report"}
    assert out["ok"] is True
    # a broken dependent anywhere in the radius blocks the gate
    calc = root / "src" / "calc.py"
    calc.write_text(calc.read_text().replace("if i.ok", "if True"))
    out = api.verify(root, store, ["Item"], radius=True)
    assert out["ok"] is False
    assert {r["name"]: r["status"] for r in out["results"]}["total"] == "fail"


def test_radius_dedupes_and_keeps_unknown_names(project):
    root, store = project
    # total's radius overlaps report's; each unit is verified once
    out = api.verify(root, store, ["total", "report"], radius=True)
    names = [r["name"] for r in out["results"]]
    assert sorted(names) == ["report", "total"] and len(names) == len(set(names))
    # a typo doesn't vanish into an empty radius — it errors and blocks
    out = api.verify(root, store, ["nope"], radius=True)
    assert out["ok"] is False
    assert out["results"][0]["error"]["code"] == "unknown_contract"


def test_radius_of_spec_only_leaf_is_vacuously_green(project):
    root, store = project
    write_contract(root, "Lonely", """
        name: Lonely
        signature: "dataclass: tag: str"
    """)
    index(root, store)
    # nothing depends on it and it has no impl: nothing invalidated, gate opens
    out = api.verify(root, store, ["Lonely"], radius=True)
    assert out == {"ok": True, "results": []}


def test_verify_flags_inferred_closure_even_on_cached_pass(project):
    root, store = project
    text = (root / "contracts" / "total.yaml").read_text()
    api.put_contract(root, store, "total", text + "status: inferred\n")
    # first run: verdict is machine-true, but it rests on an unvetted contract
    out = api.verify(root, store, ["total", "report"])
    by_name = {r["name"]: r for r in out["results"]}
    assert by_name["total"]["status"] == "pass"
    assert by_name["total"]["inferred"] == ["total"]
    assert by_name["report"]["inferred"] == ["total"]  # transitive dep is inferred
    # the flag is computed outside the cache key, so cached-pass carries it too
    out = api.verify(root, store, ["total"])
    assert out["results"][0]["status"] == "cached-pass"
    assert out["results"][0]["inferred"] == ["total"]


def test_confirming_inferred_contract_keeps_cached_green(project):
    root, store = project
    text = (root / "contracts" / "total.yaml").read_text()
    api.put_contract(root, store, "total", text + "status: inferred\n")
    assert statuses(api.verify(root, store, ["total", "report"])) == {"total": "pass", "report": "pass"}
    runs_before = store.counters()["test_runs"]
    # the review flip: inferred -> confirmed must not bust any cached green
    api.put_contract(root, store, "total", text)
    out = api.verify(root, store, ["total", "report"])
    assert statuses(out) == {"total": "cached-pass", "report": "cached-pass"}
    assert store.counters()["test_runs"] == runs_before
    assert all("inferred" not in r for r in out["results"])


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
