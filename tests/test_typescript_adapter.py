"""The TypeScript adapter end to end: hand-written canonical-AST impl hashing
(stable under formatting, sensitive to behaviour) and the auto-detected runner
(here Node's built-in node:test) via the verify flow.

`typescript` is resolved from the project's own node_modules, so the fixture
symlinks hashloom's dev typescript into each tmp project. The suite skips cleanly
when node or that typescript is unavailable (mirrors the Go suite skipping
without `go`)."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from hashloom import api
from hashloom.errors import HashloomError
from hashloom.indexer import index
from hashloom.langs import adapter_for
from hashloom.project import db_path, init_project
from hashloom.store import SqliteStore

_REPO = Path(__file__).resolve().parents[1]
_TS_PKG = _REPO / "node_modules" / "typescript"
pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not _TS_PKG.exists(),
    reason="node and a local typescript install (npm install) required",
)

_IMPL = "calc/calc.ts::Total"
_GOOD = (
    "export function Total(xs: number[]): number {\n"
    "  let s = 0;\n"
    "  for (const x of xs) { s += x; }\n"
    "  return s;\n"
    "}\n"
)


def _ts_project(root: Path) -> None:
    init_project(root)
    (root / "package.json").write_text('{\n  "type": "module"\n}\n')
    # typescript is resolved from the project; symlink hashloom's dev copy in
    (root / "node_modules").mkdir(exist_ok=True)
    (root / "node_modules" / "typescript").symlink_to(_TS_PKG)
    (root / "calc").mkdir()
    (root / "calc" / "calc.ts").write_text(_GOOD)
    (root / "calc" / "calc.test.ts").write_text(
        'import { test } from "node:test";\n'
        'import assert from "node:assert";\n'
        'import { Total } from "./calc.ts";\n'
        'test("Total sums", () => { assert.strictEqual(Total([1, 2]), 3); });\n'
    )
    (root / "contracts" / "calc.yaml").write_text(textwrap.dedent("""
        name: calc
        signature: "function Total(xs: number[]): number"
        tests: ["calc/calc.test.ts::Total sums"]
        impl: calc/calc.ts::Total
    """).strip() + "\n")


def test_ts_impl_hash_stable_under_formatting_but_not_behaviour(tmp_path):
    _ts_project(tmp_path)
    a = adapter_for(_IMPL)
    base = a.impl_hash(tmp_path, _IMPL)
    # reformat + add comment/doc + drop `export`, same behaviour -> same hash
    (tmp_path / "calc" / "calc.ts").write_text(
        "/** Total sums xs. */\n// reflowed\nfunction Total(xs: number[]): number {\n"
        "      let s=0\n  for (const x of xs) { s += x } // c\n      return s }\n"
    )
    assert a.impl_hash(tmp_path, _IMPL) == base
    # behaviour change (+= -> -=) -> different hash
    (tmp_path / "calc" / "calc.ts").write_text(_GOOD.replace("s += x", "s -= x"))
    assert a.impl_hash(tmp_path, _IMPL) != base


def test_ts_verify_pass_then_cached(tmp_path):
    _ts_project(tmp_path)
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        assert api.verify(tmp_path, store, ["calc"])["results"][0]["status"] == "pass"
        assert api.verify(tmp_path, store, ["calc"])["results"][0]["status"] == "cached-pass"
        # the impl source blob was stored (serve weft)
        assert "function Total" in store.get_blob(store.get_impl("calc")["blob_hash"])
    finally:
        store.close()


def test_ts_verify_fail_has_summary(tmp_path):
    _ts_project(tmp_path)
    (tmp_path / "calc" / "calc.ts").write_text(_GOOD.replace("return s", "return s + 1"))  # wrong result
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        r = api.verify(tmp_path, store, ["calc"])["results"][0]
        assert r["status"] == "fail"
        assert "Total sums" in r.get("summary", "")
    finally:
        store.close()


def test_ts_tests_fail_to_run_is_a_runner_error(tmp_path):
    _ts_project(tmp_path)
    # the test file loads a module that does not exist: nothing runs -> runner error
    # (an undefined *name* would just be a normal failing test under strip-types)
    (tmp_path / "calc" / "calc.test.ts").write_text(
        'import "./does-not-exist.ts";\n'
        'import { test } from "node:test";\n'
        'import { Total } from "./calc.ts";\n'
        'test("Total sums", () => { Total([1, 2]); });\n'
    )
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        r = api.verify(tmp_path, store, ["calc"])["results"][0]
        assert r["status"] == "error"
        assert r["error"]["code"] == "tests_failed_to_run"
    finally:
        store.close()


def test_ts_impl_syntax_error(tmp_path):
    _ts_project(tmp_path)
    (tmp_path / "calc" / "calc.ts").write_text("export function Total( {\n")
    with pytest.raises(HashloomError) as e:
        adapter_for(_IMPL).impl_hash(tmp_path, _IMPL)
    assert e.value.code == "impl_syntax_error"


def test_ts_runner_autodetect(tmp_path):
    """The runner is auto-detected from package.json: vitest/jest if declared,
    else Node's built-in node:test."""
    from hashloom.langs.typescript import TypeScriptAdapter

    a = TypeScriptAdapter()
    pkg = tmp_path / "package.json"

    pkg.write_text('{"type": "module"}')
    assert a._detect_runner(tmp_path) == "node"
    pkg.write_text('{"devDependencies": {"vitest": "^1.0.0"}}')
    assert a._detect_runner(tmp_path) == "vitest"
    pkg.write_text('{"dependencies": {"jest": "^29.0.0"}}')
    assert a._detect_runner(tmp_path) == "jest"
    pkg.write_text('{"devDependencies": {"vitest": "1", "jest": "29"}}')
    assert a._detect_runner(tmp_path) == "vitest"  # vitest wins
    pkg.write_text("not json at all")
    assert a._detect_runner(tmp_path) == "node"  # malformed -> safe default
