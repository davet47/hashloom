"""The Go adapter end to end: stdlib-AST impl hashing (stable under formatting,
sensitive to behaviour) and the `go test -json` runner via the verify flow."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from heddle import api
from heddle.errors import HeddleError
from heddle.indexer import index
from heddle.langs import adapter_for
from heddle.project import db_path, init_project
from heddle.store import SqliteStore

pytestmark = pytest.mark.skipif(shutil.which("go") is None, reason="go toolchain not installed")

_IMPL = "calc/calc.go::Total"
_GOOD = "package calc\n\nfunc Total(xs []int) int {\n    s := 0\n    for _, x := range xs {\n        s += x\n    }\n    return s\n}\n"


def _go_project(root: Path) -> None:
    init_project(root)
    (root / "go.mod").write_text("module calcproj\n\ngo 1.21\n")
    (root / "calc").mkdir()
    (root / "calc" / "calc.go").write_text(_GOOD)
    (root / "calc" / "calc_test.go").write_text(
        'package calc\n\nimport "testing"\n\n'
        "func TestTotal(t *testing.T) {\n"
        "    if Total([]int{1, 2}) != 3 {\n"
        '        t.Fatalf("got %d, want 3", Total([]int{1, 2}))\n'
        "    }\n}\n"
    )
    (root / "contracts" / "calc.yaml").write_text(textwrap.dedent("""
        name: calc
        signature: "func Total(xs []int) int"
        tests: [calc/calc_test.go::TestTotal]
        impl: calc/calc.go::Total
    """).strip() + "\n")


def test_go_impl_hash_stable_under_formatting_but_not_behaviour(tmp_path):
    _go_project(tmp_path)
    a = adapter_for(_IMPL)
    base = a.impl_hash(tmp_path, _IMPL)
    # reformat + add comment/doc, same behaviour -> same hash
    (tmp_path / "calc" / "calc.go").write_text(
        "package calc\n\n// Total sums xs.\nfunc Total(xs []int) int {\n  s := 0\n"
        "  for _, x := range xs { s += x } // reflowed\n  return s\n}\n"
    )
    assert a.impl_hash(tmp_path, _IMPL) == base
    # behaviour change (+= -> -=) -> different hash
    (tmp_path / "calc" / "calc.go").write_text(_GOOD.replace("s += x", "s -= x"))
    assert a.impl_hash(tmp_path, _IMPL) != base


def test_go_verify_pass_then_cached(tmp_path):
    _go_project(tmp_path)
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        assert api.verify(tmp_path, store, ["calc"])["results"][0]["status"] == "pass"
        assert api.verify(tmp_path, store, ["calc"])["results"][0]["status"] == "cached-pass"
        # the impl source blob was stored (serve weft)
        assert "func Total" in store.get_blob(store.get_impl("calc")["blob_hash"])
    finally:
        store.close()


def test_go_verify_fail_has_summary(tmp_path):
    _go_project(tmp_path)
    (tmp_path / "calc" / "calc.go").write_text(_GOOD.replace("return s", "return s + 1"))  # compiles, wrong result
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        r = api.verify(tmp_path, store, ["calc"])["results"][0]
        assert r["status"] == "fail"
        assert "TestTotal" in r.get("summary", "")
    finally:
        store.close()


def test_go_build_error_is_a_runner_error(tmp_path):
    _go_project(tmp_path)
    # parses fine, but references an undefined name: compiles -> fail at test build
    (tmp_path / "calc" / "calc.go").write_text(
        "package calc\n\nfunc Total(xs []int) int {\n    return nope(xs)\n}\n"
    )
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        r = api.verify(tmp_path, store, ["calc"])["results"][0]
        assert r["status"] == "error"
        assert r["error"]["code"] == "tests_failed_to_run"
    finally:
        store.close()


def test_go_impl_syntax_error(tmp_path):
    _go_project(tmp_path)
    (tmp_path / "calc" / "calc.go").write_text("package calc\n\nfunc Total( {\n")
    with pytest.raises(HeddleError) as e:
        adapter_for(_IMPL).impl_hash(tmp_path, _IMPL)
    assert e.value.code == "impl_syntax_error"
