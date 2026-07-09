"""The toolchain identity is folded into the verification key, so a green is only
served when the toolchain matches — the soundness layer under the shared cache. A
toolchain change busts the cache (verify re-runs) and `status` agrees (it computes
the same key component). The Go/TS adapters' own toolchain_identity is exercised
by their verify-pass-then-cached suites; here we pin the Python path and the key."""

from __future__ import annotations

import textwrap
from pathlib import Path

from hashloom import api
from hashloom.indexer import index
from hashloom.langs import adapter_for
from hashloom.langs.python import PythonAdapter
from hashloom.project import db_path, init_project
from hashloom.store import SqliteStore
from hashloom.verify import verification_key


def _project(root: Path) -> None:
    init_project(root)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "__init__.py").write_text("")
    (root / "tests" / "__init__.py").write_text("")
    (root / "contracts" / "total.yaml").write_text(textwrap.dedent("""
        name: total
        signature: "(xs: list[int]) -> int"
        tests: [tests/test_x.py::test_total]
        impl: src/x.py::total
    """).strip() + "\n")
    (root / "src" / "x.py").write_text("def total(xs):\n    return sum(xs)\n")
    (root / "tests" / "test_x.py").write_text(
        "from src.x import total\n\n\ndef test_total():\n    assert total([1, 2]) == 3\n"
    )


def test_verification_key_includes_the_toolchain(tmp_path):
    _project(tmp_path)
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        k_a = verification_key(store, "total", "ih", "th", "python 3.11.7")
        k_b = verification_key(store, "total", "ih", "th", "python 3.13.5")
        k_a2 = verification_key(store, "total", "ih", "th", "python 3.11.7")
        assert k_a != k_b          # a different toolchain -> a different key
        assert k_a == k_a2         # the same toolchain -> the same key
    finally:
        store.close()


def test_toolchain_change_busts_cache_and_status_agrees(tmp_path, monkeypatch):
    _project(tmp_path)
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        # baseline: verified, cached, and status sees it clean under the real toolchain
        assert api.verify(tmp_path, store, ["total"])["results"][0]["status"] == "pass"
        assert api.verify(tmp_path, store, ["total"])["results"][0]["status"] == "cached-pass"
        assert "total" not in api.status(tmp_path, store)["dirty"]

        # the toolchain identity changes (e.g. a Python upgrade)
        monkeypatch.setattr(PythonAdapter, "toolchain_identity",
                            lambda self, root, override=None: "python 0.0.0")

        # status flips to dirty immediately: the prior green is for a different key
        assert "total" in api.status(tmp_path, store)["dirty"]
        # and verify re-runs rather than serving the old-toolchain green
        assert api.verify(tmp_path, store, ["total"])["results"][0]["status"] == "pass"
    finally:
        store.close()


def test_python_toolchain_identity_format(tmp_path):
    ident = adapter_for("x.py::total").toolchain_identity(tmp_path)
    assert ident.startswith("python ")
    assert ident.split()[1][0].isdigit()  # e.g. "python 3.13.5"
