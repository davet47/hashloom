"""The Python adapter: ast-based hashing and the pytest runner (heddle's
original behaviour, now behind the LanguageAdapter interface)."""

from __future__ import annotations

from pathlib import Path

from .. import implhash, verify
from ..config import resolve_python


class PythonAdapter:
    def impl_hash(self, root: Path, impl: str, contract: str | None = None) -> str:
        return implhash.impl_hash(root, impl, contract=contract)

    def test_source_hash(self, root: Path, node_ids: list[str]) -> str:
        return implhash.test_source_hash(root, node_ids)

    def impl_source(self, root: Path, impl: str) -> str | None:
        path = root / impl.partition("::")[0]
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def resolve_toolchain(self, root: Path, override: str | None = None) -> str:
        return resolve_python(root, override=override)

    def run_tests(
        self, root: Path, node_ids: list[str], toolchain: str, timeout: int | float
    ) -> tuple[bool, str]:
        ok, out = verify._run_pytest(root, node_ids, toolchain, timeout)
        return ok, ("" if ok else verify._failure_summary(out))
