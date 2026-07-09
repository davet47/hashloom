"""The Go adapter: a stdlib `go/ast` hash helper plus the `go test -json` runner.

Both seams come from Go's standard library, so hashloom writes no hand-rolled
hash code. The AST-hash helper lives in `gohash/` and is driven with `go run`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .. import tokens
from ..config import load_config
from ..errors import HashloomError
from . import SUMMARY_MAX_TOKENS

_GOHASH_DIR = Path(__file__).parent / "gohash"
_GO_FILE_LINE = re.compile(r"[^\s:]+\.go:\d+:")  # a `file.go:NN:` location in test output
_GO_VERSION = re.compile(r"go version go(\S+)")  # `go version go1.21.5 darwin/arm64`


def _oneline(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


class GoAdapter:
    def __init__(self) -> None:
        self._go_cache: dict[tuple[str, str | None], str] = {}
        self._id_cache: dict[tuple[str, str | None], str] = {}

    # -- toolchain ----------------------------------------------------------

    def resolve_toolchain(self, root: Path, override: str | None = None) -> str:
        return self._go(root, override)

    def _go(self, root: Path, override: str | None = None) -> str:
        key = (str(root), override)
        if key in self._go_cache:
            return self._go_cache[key]
        cand = override or load_config(root).get("go") or shutil.which("go")
        if not cand:
            raise HashloomError(
                "bad_toolchain",
                "no Go toolchain found (install go, or set 'go' in .hashloom/config.json)",
            )
        try:
            subprocess.run([cand, "version"], capture_output=True, check=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            raise HashloomError("bad_toolchain", f"'{cand}' is not a working Go toolchain")
        self._go_cache[key] = cand
        return cand

    def toolchain_identity(self, root: Path, override: str | None = None) -> str:
        key = (str(root), override)
        if key in self._id_cache:
            return self._id_cache[key]
        go = self._go(root, override)
        try:
            proc = subprocess.run(
                [go, "version"], capture_output=True, text=True, check=True, timeout=30,
                env={**os.environ, "GOTOOLCHAIN": "local"},
            )
        except (OSError, subprocess.SubprocessError):
            raise HashloomError("bad_toolchain", f"could not read the Go version from '{go}'")
        m = _GO_VERSION.search(proc.stdout)
        # version only (drop the trailing GOOS/GOARCH) so cross-OS greens share
        ident = f"go {m.group(1)}" if m else f"go {_oneline(proc.stdout)}"
        self._id_cache[key] = ident
        return ident

    # -- hashing (via the go/ast helper) ------------------------------------

    def impl_hash(self, root: Path, impl: str, contract: str | None = None) -> str:
        path_str, _, qual = impl.partition("::")
        return self._hash_def(root, path_str, qual, contract=contract)

    def _hash_def(self, root: Path, path_str: str, qual: str, contract: str | None = None) -> str:
        go = self._go(root)
        proc = subprocess.run(
            [go, "run", ".", str(root / path_str), qual],
            cwd=_GOHASH_DIR, capture_output=True, text=True, timeout=120,
            env={**os.environ, "GOTOOLCHAIN": "local"},
        )
        kind, _, rest = proc.stdout.strip().partition(" ")
        if kind == "hash":
            return rest
        if kind == "not_found":
            raise HashloomError("impl_not_found", rest, contract=contract)
        if kind == "syntax":
            raise HashloomError("impl_syntax_error", rest, contract=contract)
        # the helper itself could not run (go missing, helper build error, ...)
        raise HashloomError(
            "tests_failed_to_run",
            tokens.truncate("go ast helper failed: " + _oneline(proc.stderr or proc.stdout), 60),
        )

    def test_source_hash(self, root: Path, node_ids: list[str]) -> str:
        parts = []
        for nid in sorted(node_ids):
            path_str, _, test = nid.partition("::")
            h = None
            if path_str and test:
                try:
                    h = self._hash_def(root, path_str, test)
                except (HashloomError, OSError, ValueError, subprocess.SubprocessError):
                    h = None
            parts.append(f"{nid}={h or 'id'}")
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def impl_source(self, root: Path, impl: str) -> str | None:
        path = root / impl.partition("::")[0]
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    # -- running tests (go test -json) --------------------------------------

    def run_tests(
        self, root: Path, node_ids: list[str], toolchain: str, timeout: int | float
    ) -> tuple[bool, str]:
        # a Go test node id is "path/to/file_test.go::TestName"; the package is
        # the file's directory, addressed by -run '^(TestA|TestB)$'
        by_pkg: dict[str, list[str]] = {}
        for nid in node_ids:
            path_str, _, test = nid.partition("::")
            parent = Path(path_str).parent
            pkg = "." if str(parent) == "." else "./" + parent.as_posix()
            by_pkg.setdefault(pkg, []).append(test)

        failed = False
        summary = ""
        for pkg, tests in by_pkg.items():
            run_re = "^(" + "|".join(re.escape(t) for t in tests) + ")$"
            proc = subprocess.run(
                [toolchain, "test", "-json", "-run", run_re, pkg],
                cwd=root, capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "GOTOOLCHAIN": "local"},
            )
            events = []
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            test_fails = [e for e in events if e.get("Action") == "fail" and e.get("Test")]
            # non-zero exit with no per-test failure means a build/run error, not a fail
            if proc.returncode != 0 and not test_fails:
                raise HashloomError(
                    "tests_failed_to_run",
                    tokens.truncate("go test could not run: " + _oneline(proc.stdout + " " + proc.stderr), 60),
                )
            if test_fails and not summary:
                failed = True
                summary = self._summarise(events, test_fails[0].get("Test"))
            elif test_fails:
                failed = True
        return (not failed, summary)

    def _summarise(self, events: list[dict], test: str | None) -> str:
        for e in events:
            if e.get("Test") == test and e.get("Action") == "output":
                out = e.get("Output", "")
                if _GO_FILE_LINE.search(out):
                    return tokens.truncate(f"{test}: " + _oneline(out), SUMMARY_MAX_TOKENS)
        return tokens.truncate(f"{test} failed", SUMMARY_MAX_TOKENS)
