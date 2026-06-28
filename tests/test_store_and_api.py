"""Store, indexer, dep graph, and the non-verify tools."""

import pytest

from heddle import api
from heddle.errors import HeddleError
from heddle.indexer import index

from .conftest import write_contract


def test_index_builds_graph(project):
    root, store = project
    assert store.contract_names() == ["Item", "report", "total"]
    assert store.deps_of("report") == ["Item", "total"]
    assert store.dependents_of("Item", transitive=True) == ["report", "total"]
    assert store.dependents_of("total") == ["report"]


def test_index_rejects_unknown_dep(project):
    root, store = project
    write_contract(root, "bad", """
        name: bad
        signature: "() -> None"
        deps: [Itme]
    """)
    with pytest.raises(HeddleError) as exc:
        index(root, store)
    assert exc.value.code == "unknown_dep"
    # the 3am error: a nearest-match hint, not a KeyError
    assert "'Itme' not found" in exc.value.message
    assert "nearest: 'Item'" in exc.value.message


def test_reindex_is_stable(project):
    root, store = project
    before = store.contract_hashes()
    result = index(root, store)
    assert result["changed"] == []
    assert store.contract_hashes() == before


def test_get_contract_packet(project):
    root, store = project
    packet = api.get_contract(root, store, "report")
    assert packet["name"] == "report"
    assert packet["contract"]["signature"] == "(items: list[Item]) -> str"
    assert {d["name"] for d in packet["deps"]} == {"Item", "total"}
    assert all("signature" in d and "hash" in d for d in packet["deps"])
    assert packet["callers"] == []
    assert api.get_contract(root, store, "Item")["callers"] == ["report", "total"]


def test_get_contract_unknown_suggests_nearest(project):
    root, store = project
    with pytest.raises(HeddleError) as exc:
        api.get_contract(root, store, "reprot")
    assert exc.value.code == "unknown_contract"
    assert "report" in exc.value.message


def test_get_dependents(project):
    root, store = project
    out = api.get_dependents(root, store, "Item", transitive=True)
    assert [d["name"] for d in out["dependents"]] == ["report", "total"]
    assert all(d["hash"] for d in out["dependents"])
    assert [d["name"] for d in api.get_dependents(root, store, "total")["dependents"]] == ["report"]


def test_put_contract_writes_file_and_invalidates(project):
    root, store = project
    old_hash = store.get_contract("total")["hash"]
    new_yaml = (root / "contracts" / "total.yaml").read_text().replace(
        "(items: list[Item]) -> float", "(items: list[Item]) -> int"
    )
    out = api.put_contract(root, store, "total", new_yaml)
    assert out["changed"] is True
    assert out["hash"] != old_hash
    assert out["invalidated"] == ["report"]
    assert (root / "contracts" / "total.yaml").read_text() == new_yaml


def test_put_contract_unchanged_content_invalidates_nothing(project):
    root, store = project
    text = (root / "contracts" / "total.yaml").read_text()
    out = api.put_contract(root, store, "total", text + "\n# trailing comment\n")
    assert out["changed"] is False
    assert out["invalidated"] == []


def test_put_contract_rejects_unknown_dep(project):
    root, store = project
    with pytest.raises(HeddleError) as exc:
        api.put_contract(root, store, "thing", 'name: thing\nsignature: "() -> None"\ndeps: [Itme]\n')
    assert exc.value.code == "unknown_dep"
    assert "Item" in exc.value.message


def test_put_contract_rejects_self_dep(project):
    root, store = project
    with pytest.raises(HeddleError) as exc:
        api.put_contract(root, store, "loop", 'name: loop\nsignature: "() -> None"\ndeps: [loop]\n')
    assert exc.value.code == "invalid_shape"


def test_contract_removal_reindexes(project):
    root, store = project
    (root / "contracts" / "report.yaml").unlink()
    result = index(root, store)
    assert result["removed"] == ["report"]
    assert store.contract_names() == ["Item", "total"]


def test_status_caches_impl_hashes(project, monkeypatch):
    root, store = project
    from heddle import implhash

    calls = {"n": 0}
    real = implhash.impl_hash

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    # the Python adapter calls implhash.impl_hash; patch it there
    monkeypatch.setattr(implhash, "impl_hash", counting)
    api.status(root, store)
    first = calls["n"]
    assert first == 2  # total and report have impls; Item is spec-only
    api.status(root, store)
    assert calls["n"] == first  # second call served from the impl-hash cache


def test_status_cache_invalidates_on_impl_edit(project):
    root, store = project
    api.verify(root, store, ["total", "report"])
    assert api.status(root, store)["dirty"] == []  # warms the cache while green
    calc = root / "src" / "calc.py"
    # behaviour-preserving rewrite: changes the AST (and size), so the cached
    # impl hash must invalidate and the now-unverified key shows up as dirty
    calc.write_text(calc.read_text().replace(
        "return sum(i.value for i in items if i.ok)",
        "vals = [i.value for i in items if i.ok]\n    return sum(vals)",
    ))
    assert "total" in api.status(root, store)["dirty"]


def test_index_populates_impl_blobs(project):
    root, store = project
    total, report = store.get_impl("total"), store.get_impl("report")
    assert total["blob_hash"] is not None
    # total and report share src/calc.py, so the blob is deduped to one hash
    assert total["blob_hash"] == report["blob_hash"]
    src = store.get_blob(total["blob_hash"])
    assert "def total(" in src and "def report(" in src


def test_put_blob_is_content_addressed_and_round_trips(tmp_path):
    from heddle.project import db_path, init_project
    from heddle.store import SqliteStore

    init_project(tmp_path)
    store = SqliteStore(db_path(tmp_path))
    try:
        h = store.put_blob("def f():\n    return 1\n")
        assert store.get_blob(h) == "def f():\n    return 1\n"
        assert store.put_blob("def f():\n    return 1\n") == h  # idempotent / deduped
        assert store.get_blob("0" * 64) is None
    finally:
        store.close()
