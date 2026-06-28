"""Per-language adapters.

Each adapter knows how to, for one language: hash an implementation's normalised
AST, hash a test's source, read impl source for the content-addressed blob,
resolve the language's toolchain, and run tests. Python is the default; Go is the
first non-Python adapter.

The adapter is chosen by the impl file's extension (`adapter_for`), so contracts
gain no new syntax: a `.go` impl routes to Go, everything else to Python.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

# every adapter's failure summary is capped here, never a traceback
SUMMARY_MAX_TOKENS = 40


class LanguageAdapter(Protocol):
    def impl_hash(self, root: Path, impl: str, contract: str | None = None) -> str: ...
    def test_source_hash(self, root: Path, node_ids: list[str]) -> str: ...
    def impl_source(self, root: Path, impl: str) -> str | None: ...
    def resolve_toolchain(self, root: Path, override: str | None = None) -> str: ...
    def run_tests(
        self, root: Path, node_ids: list[str], toolchain: str, timeout: int | float
    ) -> tuple[bool, str]: ...


_PYTHON: LanguageAdapter | None = None
_GO: LanguageAdapter | None = None


def adapter_for(impl: str) -> LanguageAdapter:
    """Pick the adapter by the impl file's extension; default to Python."""
    global _PYTHON, _GO
    path = impl.partition("::")[0]
    if path.endswith(".go"):
        if _GO is None:
            from .go import GoAdapter

            _GO = GoAdapter()
        return _GO
    if _PYTHON is None:
        from .python import PythonAdapter

        _PYTHON = PythonAdapter()
    return _PYTHON
