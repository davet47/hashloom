"""The Python adapter: ast-based hashing and the pytest runner (hashloom's
original behaviour, now behind the LanguageAdapter interface)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import implhash, verify
from ..config import resolve_python
from ..errors import HashloomError


class PythonAdapter:
    def __init__(self) -> None:
        self._id_cache: dict[tuple[str, str | None], str] = {}

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

    def toolchain_identity(self, root: Path, override: str | None = None) -> str:
        # the resolved interpreter may differ from the one running hashloom, so ask
        # it directly; version-only (no platform) keeps cross-OS greens shareable
        key = (str(root), override)
        if key in self._id_cache:
            return self._id_cache[key]
        python = self.resolve_toolchain(root, override)
        try:
            proc = subprocess.run(
                [python, "-c", "import platform;print(platform.python_version())"],
                capture_output=True, text=True, check=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            raise HashloomError("bad_toolchain", f"could not read the Python version from '{python}'")
        ident = f"python {proc.stdout.strip()}"
        self._id_cache[key] = ident
        return ident

    def run_tests(
        self, root: Path, node_ids: list[str], toolchain: str, timeout: int | float
    ) -> tuple[bool, str]:
        ok, out = verify._run_pytest(root, node_ids, toolchain, timeout)
        return ok, ("" if ok else verify._failure_summary(out))
