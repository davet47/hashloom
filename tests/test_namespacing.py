"""Subdirectories under contracts/ act as namespaces — ISSUES: contract names
are global. `contracts/ns/foo.yaml` is the contract `ns/foo`; the same short
name can coexist in different folders. Names that would escape contracts/ are
refused."""

from __future__ import annotations

import textwrap

import pytest

from heddle import api
from heddle.contract import parse_contract
from heddle.errors import HeddleError
from heddle.indexer import index
from heddle.project import db_path, init_project
from heddle.store import SqliteStore


def _project(tmp_path):
    init_project(tmp_path)
    return tmp_path, SqliteStore(db_path(tmp_path))


def _write(root, relpath: str, body: str) -> None:
    f = root / "contracts" / relpath
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(textwrap.dedent(body).strip() + "\n")


def test_nested_contract_indexes_with_namespaced_name(tmp_path):
    root, store = _project(tmp_path)
    _write(root, "billing/Invoice.yaml", """
        name: billing/Invoice
        signature: "dataclass: total: float"
    """)
    index(root, store)
    assert store.contract_names() == ["billing/Invoice"]


def test_cross_namespace_dependency_resolves(tmp_path):
    root, store = _project(tmp_path)
    _write(root, "core/Money.yaml", """
        name: core/Money
        signature: "dataclass: cents: int"
    """)
    _write(root, "billing/Invoice.yaml", """
        name: billing/Invoice
        signature: "(amount: Money) -> Invoice"
        deps: [core/Money]
    """)
    index(root, store)
    assert store.deps_of("billing/Invoice") == ["core/Money"]
    packet = api.get_contract(root, store, "billing/Invoice")
    assert [d["name"] for d in packet["deps"]] == ["core/Money"]


def test_same_stem_in_two_namespaces_coexist(tmp_path):
    root, store = _project(tmp_path)
    _write(root, "a/Thing.yaml", 'name: a/Thing\nsignature: "() -> A"\n')
    _write(root, "b/Thing.yaml", 'name: b/Thing\nsignature: "() -> B"\n')
    index(root, store)
    assert store.contract_names() == ["a/Thing", "b/Thing"]
    # distinct identities -> distinct hashes
    hashes = store.contract_hashes()
    assert hashes["a/Thing"] != hashes["b/Thing"]


def test_put_contract_creates_namespace_directory(tmp_path):
    root, store = _project(tmp_path)
    out = api.put_contract(root, store, "ns/New", 'name: ns/New\nsignature: "() -> None"\n')
    assert out["name"] == "ns/New"
    assert (root / "contracts" / "ns" / "New.yaml").is_file()
    assert store.get_contract("ns/New") is not None


def test_flat_names_still_work(tmp_path):
    root, store = _project(tmp_path)
    _write(root, "Plain.yaml", 'name: Plain\nsignature: "() -> None"\n')
    index(root, store)
    assert store.contract_names() == ["Plain"]


@pytest.mark.parametrize("bad", ["../evil", "/etc/passwd", "a/../../b", "ns//x"])
def test_parse_rejects_unsafe_names(bad):
    with pytest.raises(HeddleError) as e:
        parse_contract(f'name: "{bad}"\nsignature: "() -> None"\n')
    assert e.value.code == "invalid_name"


def test_parse_rejects_backslash_name():
    with pytest.raises(HeddleError) as e:
        parse_contract("name: 'a\\\\b'\nsignature: \"() -> None\"\n")
    assert e.value.code == "invalid_name"


def test_put_contract_rejects_escaping_name(tmp_path):
    root, store = _project(tmp_path)
    with pytest.raises(HeddleError) as e:
        api.put_contract(root, store, "../evil", 'name: "../evil"\nsignature: "() -> None"\n')
    assert e.value.code in ("invalid_name", "unsafe_name")
    assert not (root.parent / "evil.yaml").exists()  # nothing written outside contracts/


# --- review follow-ups: stray files, collisions, symlink escape, coverage ---


def test_stray_non_contract_yaml_is_skipped_not_fatal(tmp_path):
    root, store = _project(tmp_path)
    _write(root, "core/Money.yaml", 'name: core/Money\nsignature: "() -> M"\n')
    # clutter under contracts/ that must NOT abort indexing:
    (root / "contracts" / "data.yaml").write_text("foo: bar\n")  # name-less doc
    _write(root, "fixtures/sample.yaml", "items: [1, 2, 3]\n")  # nested non-contract
    (root / "contracts" / ".cache").mkdir()
    (root / "contracts" / ".cache" / "junk.yaml").write_text("k: v\n")  # hidden dir
    # config files that carry a top-level name: (mkdocs, CI, compose) but no
    # signature: are not contracts and must be skipped, not aborted
    (root / "contracts" / "mkdocs.yaml").write_text("name: My Site\nnav: [a, b]\n")
    _write(root, "deploy/ci.yaml", "name: CI\njobs: {}\n")
    result = index(root, store)
    assert result["indexed"] == 1
    assert store.contract_names() == ["core/Money"]


def test_duplicate_name_from_yaml_and_yml_is_rejected(tmp_path):
    root, store = _project(tmp_path)
    _write(root, "ns/thing.yaml", 'name: ns/thing\nsignature: "() -> A"\n')
    _write(root, "ns/thing.yml", 'name: ns/thing\nsignature: "() -> B"\n')
    with pytest.raises(HeddleError) as e:
        index(root, store)
    assert e.value.code == "duplicate_contract"


def _case_insensitive_fs(path) -> bool:
    probe = path / "CaseProbe.tmp"
    probe.write_text("x")
    try:
        return (path / "caseprobe.tmp").exists()
    finally:
        probe.unlink()


def test_case_variant_names_handled_per_filesystem(tmp_path):
    root, store = _project(tmp_path)
    api.put_contract(root, store, "billing/Invoice", 'name: billing/Invoice\nsignature: "() -> A"\n')
    body = 'name: billing/invoice\nsignature: "() -> B"\n'
    if _case_insensitive_fs(root):
        # same file on disk: refuse, don't silently clobber + split store from disk
        with pytest.raises(HeddleError) as e:
            api.put_contract(root, store, "billing/invoice", body)
        assert e.value.code == "name_collision"
        assert "billing/Invoice" in store.contract_names()
        assert index(root, SqliteStore(db_path(root)))["indexed"] == 1  # store stays rebuildable
    else:
        api.put_contract(root, store, "billing/invoice", body)  # genuinely distinct files
        assert set(store.contract_names()) == {"billing/Invoice", "billing/invoice"}


def test_lock_key_is_injective_for_slash_vs_double_underscore():
    from heddle.project import _lock_key

    assert _lock_key("a/b") != _lock_key("a__b")


def test_symlink_escape_is_refused(tmp_path):
    root, store = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "contracts" / "escape").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not support symlinks")
    with pytest.raises(HeddleError) as e:
        api.put_contract(root, store, "escape/evil", 'name: escape/evil\nsignature: "() -> None"\n')
    assert e.value.code == "unsafe_name"
    assert not (outside / "evil.yaml").exists()  # nothing written outside contracts/


def test_namespaced_name_mismatch_is_rejected(tmp_path):
    root, store = _project(tmp_path)
    _write(root, "billing/invoice.yaml", 'name: invoice\nsignature: "() -> None"\n')  # missing ns prefix
    with pytest.raises(HeddleError) as e:
        index(root, store)
    assert e.value.code == "name_mismatch"


def test_nested_yml_extension_indexes(tmp_path):
    root, store = _project(tmp_path)
    _write(root, "ns/thing.yml", 'name: ns/thing\nsignature: "() -> None"\n')
    index(root, store)
    assert store.contract_names() == ["ns/thing"]


def test_nested_contract_removal_reindexes(tmp_path):
    root, store = _project(tmp_path)
    _write(root, "core/money.yaml", 'name: core/money\nsignature: "() -> M"\n')
    _write(root, "billing/invoice.yaml", 'name: billing/invoice\nsignature: "(m: money) -> I"\ndeps: [core/money]\n')
    index(root, store)
    (root / "contracts" / "billing" / "invoice.yaml").unlink()
    result = index(root, store)
    assert result["removed"] == ["billing/invoice"]
    assert store.contract_names() == ["core/money"]


def test_rejected_name_writes_nothing(tmp_path):
    root, store = _project(tmp_path)
    cdir = root / "contracts"
    before = sorted(p.name for p in cdir.rglob("*"))
    with pytest.raises(HeddleError):
        api.put_contract(root, store, "../evil", 'name: "../evil"\nsignature: "() -> None"\n')
    assert store.get_contract("../evil") is None
    assert sorted(p.name for p in cdir.rglob("*")) == before  # no file, no stray .tmp
