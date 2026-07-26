"""The adapter seam: extension routing, protocol conformance, capped summaries.

These are the tests behind contracts/LanguageAdapter.yaml, so they must run
without any non-Python toolchain installed — construction is lazy, and nothing
here shells out.
"""

from __future__ import annotations

from hashloom.langs import SUMMARY_MAX_TOKENS, adapter_for
from hashloom.langs.csharp import CSharpAdapter
from hashloom.langs.go import GoAdapter
from hashloom.langs.java import JavaAdapter
from hashloom.langs.python import PythonAdapter
from hashloom.langs.typescript import TypeScriptAdapter

_SEAM = [
    "impl_hash",
    "test_source_hash",
    "impl_source",
    "resolve_toolchain",
    "toolchain_identity",
    "run_tests",
]


def test_adapter_for_routes_by_extension_and_caches():
    assert isinstance(adapter_for("a/b.py::f"), PythonAdapter)
    assert isinstance(adapter_for("a/b.go::F"), GoAdapter)
    for ext in (".ts", ".tsx", ".mts", ".cts"):
        assert isinstance(adapter_for(f"a/b{ext}::f"), TypeScriptAdapter)
    assert isinstance(adapter_for("a/B.java::B.f"), JavaAdapter)
    assert isinstance(adapter_for("a/Calc.cs::Calc.Total"), CSharpAdapter)
    # unknown extensions fall through to the Python default, by design
    assert isinstance(adapter_for("a/b.rb::f"), PythonAdapter)
    # one singleton per language, so per-(root, override) caches are shared
    assert adapter_for("x.java::A") is adapter_for("y.java::B")
    assert adapter_for("x.go::A") is adapter_for("y.go::B")
    assert adapter_for("x.cs::A") is adapter_for("y.cs::B")


def test_every_adapter_implements_the_protocol():
    for cls in (PythonAdapter, GoAdapter, TypeScriptAdapter, JavaAdapter, CSharpAdapter):
        for name in _SEAM:
            assert callable(getattr(cls, name, None)), f"{cls.__name__}.{name}"


def test_failure_summaries_are_capped():
    # every adapter truncates failure summaries to this; a traceback never fits
    assert SUMMARY_MAX_TOKENS == 40
