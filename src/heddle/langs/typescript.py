"""The TypeScript adapter: a hand-written canonical AST hash helper (driven with
node + the project's own typescript) plus an auto-detected test runner.

Unlike Go (stdlib ``go/ast``) and Python (stdlib ``ast``), TypeScript has no
built-in AST serializer, so the helper in ``tshash/`` hand-writes the canonical
walk over the TS Compiler API. ``typescript`` is resolved from the target
project, so the hash tracks the project's own compiler version -- the same
"verify against the target's own toolchain" stance the Go and Python adapters
take.

The test runner is auto-detected from the project's ``package.json``: a ``vitest``
or ``jest`` dependency routes to that runner (both emit a jest-shaped JSON
report); otherwise heddle falls back to Node's built-in ``node:test`` (TAP), which
needs no dependency at all. The runner backends are isolated below so a project's
real runner is what verifies it.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from .. import tokens
from ..config import load_config
from ..errors import HeddleError
from . import SUMMARY_MAX_TOKENS

_TSHASH = Path(__file__).parent / "tshash" / "main.js"
_TAP_LINE = re.compile(r"^(ok|not ok) \d+ - (.*?)(?:\s+#.*)?$")


def _oneline(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


class TypeScriptAdapter:
    def __init__(self) -> None:
        self._node_cache: dict[tuple[str, str | None], str] = {}
        self._id_cache: dict[tuple[str, str | None], str] = {}

    # -- toolchain ----------------------------------------------------------

    def resolve_toolchain(self, root: Path, override: str | None = None) -> str:
        return self._node(root, override)

    def _node(self, root: Path, override: str | None = None) -> str:
        key = (str(root), override)
        if key in self._node_cache:
            return self._node_cache[key]
        cand = override or load_config(root).get("node") or shutil.which("node")
        if not cand:
            raise HeddleError(
                "bad_toolchain",
                "no Node.js toolchain found (install node, or set 'node' in .heddle/config.json)",
            )
        try:
            subprocess.run([cand, "--version"], capture_output=True, check=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            raise HeddleError("bad_toolchain", f"'{cand}' is not a working Node.js toolchain")
        self._node_cache[key] = cand
        return cand

    def toolchain_identity(self, root: Path, override: str | None = None) -> str:
        key = (str(root), override)
        if key in self._id_cache:
            return self._id_cache[key]
        node = self._node(root, override)
        try:
            nv = subprocess.run(
                [node, "--version"], capture_output=True, text=True, check=True, timeout=30
            ).stdout.strip().lstrip("v")
            # the project's own typescript (resolved from root, like the hasher)
            tv = subprocess.run(
                [node, "-p", "require('typescript').version"],
                cwd=root, capture_output=True, text=True, check=True, timeout=30,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise HeddleError("bad_toolchain", f"could not read node/typescript versions via '{node}'")
        ident = f"node {nv} ts {tv}"
        self._id_cache[key] = ident
        return ident

    # -- hashing (via the tshash helper) ------------------------------------

    def impl_hash(self, root: Path, impl: str, contract: str | None = None) -> str:
        path_str, _, qual = impl.partition("::")
        return self._hash_def(root, path_str, qual, contract=contract)

    def _hash_def(self, root: Path, path_str: str, qual: str, contract: str | None = None) -> str:
        node = self._node(root)
        proc = subprocess.run(
            [node, str(_TSHASH), str(root / path_str), qual, str(root)],
            capture_output=True, text=True, timeout=120,
        )
        kind, _, rest = proc.stdout.strip().partition(" ")
        if kind == "hash":
            return rest
        if kind == "not_found":
            raise HeddleError("impl_not_found", rest, contract=contract)
        if kind == "syntax":
            raise HeddleError("impl_syntax_error", rest, contract=contract)
        if kind == "notoolchain":
            raise HeddleError("bad_toolchain", rest, contract=contract)
        # the helper itself could not run (node missing, helper error, ...)
        raise HeddleError(
            "tests_failed_to_run",
            tokens.truncate("ts ast helper failed: " + _oneline(proc.stderr or proc.stdout), 60),
        )

    def test_source_hash(self, root: Path, node_ids: list[str]) -> str:
        parts = []
        for nid in sorted(node_ids):
            path_str, _, test = nid.partition("::")
            h = None
            if path_str and test:
                try:
                    h = self._hash_def(root, path_str, test)
                except (HeddleError, OSError, ValueError, subprocess.SubprocessError):
                    h = None
            parts.append(f"{nid}={h or 'id'}")
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def impl_source(self, root: Path, impl: str) -> str | None:
        path = root / impl.partition("::")[0]
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    # -- running tests (auto-detected runner) -------------------------------

    def run_tests(
        self, root: Path, node_ids: list[str], toolchain: str, timeout: int | float
    ) -> tuple[bool, str]:
        by_file: dict[str, list[str]] = {}
        for nid in node_ids:
            path_str, _, test = nid.partition("::")
            by_file.setdefault(path_str, []).append(test)

        runner = self._detect_runner(root)
        if runner == "vitest":
            return self._run_json_runner(root, "vitest", by_file, timeout)
        if runner == "jest":
            return self._run_json_runner(root, "jest", by_file, timeout)
        return self._run_node_test(root, toolchain, by_file, timeout)

    def _detect_runner(self, root: Path) -> str:
        """vitest / jest if a dependency declares them, else Node's node:test."""
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "node"
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "vitest" in deps:
            return "vitest"
        if "jest" in deps:
            return "jest"
        return "node"

    def _name_pattern(self, by_file: dict[str, list[str]]) -> str:
        names = [t for tests in by_file.values() for t in tests]
        return "^(" + "|".join(re.escape(n) for n in names) + ")$"

    # node:test backend (TAP) -----------------------------------------------

    def _run_node_test(
        self, root: Path, node: str, by_file: dict[str, list[str]], timeout: int | float
    ) -> tuple[bool, str]:
        requested = {t for tests in by_file.values() for t in tests}
        cmd = [
            # --experimental-strip-types runs .ts directly; it is the default on
            # Node >= 23.6 and the explicit opt-in on 22.6-23.5 (so we always pass
            # it). Below 22.6, .ts will not run and surfaces as tests_failed_to_run.
            node, "--test", "--experimental-strip-types", "--test-reporter=tap",
            "--disable-warning=ExperimentalWarning",
            "--test-name-pattern=" + self._name_pattern(by_file),
            *by_file.keys(),
        ]
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout)
        lines = proc.stdout.splitlines()
        ran: list[str] = []
        fails: list[tuple[str, str]] = []
        for i, line in enumerate(lines):
            m = _TAP_LINE.match(line.strip())
            # ignore lines for anything we didn't ask to run -- when a file fails
            # to load, node:test reports a `not ok` under the *file* name, not a
            # test name; that is a runner error, handled by the `not ran` case
            if not m or m.group(2) not in requested:
                continue
            ran.append(m.group(2))
            if m.group(1) == "not ok":
                fails.append((m.group(2), self._tap_error(lines, i)))
        if fails:
            name, detail = fails[0]
            return (False, tokens.truncate(f"{name}: {detail}", SUMMARY_MAX_TOKENS))
        if not ran:
            # no requested test produced a result: a load/parse/import error
            raise HeddleError(
                "tests_failed_to_run",
                tokens.truncate(
                    "node --test could not run: " + _oneline(proc.stderr or proc.stdout), 60
                ),
            )
        return (True, "")

    def _tap_error(self, lines: list[str], idx: int) -> str:
        """Pull the failure message out of the YAML block after a `not ok` line."""
        block = lines[idx + 1: idx + 25]
        for j, raw in enumerate(block):
            s = raw.strip()
            if s.startswith("error:"):
                inline = s[len("error:"):].strip().lstrip("|-").strip()
                if inline:
                    return _oneline(inline)
                # block scalar: the message is the next non-empty indented line(s)
                for nxt in block[j + 1:]:
                    t = nxt.strip()
                    if t and not t.endswith(":") and t not in ("...",):
                        return _oneline(t)
                break
        return "failed"

    # vitest / jest backend (jest-shaped JSON) ------------------------------

    def _run_json_runner(
        self, root: Path, runner: str, by_file: dict[str, list[str]], timeout: int | float
    ) -> tuple[bool, str]:
        binary = root / "node_modules" / ".bin" / runner
        base = [str(binary)] if binary.exists() else ["npx", runner]
        if runner == "vitest":
            cmd = [*base, "run", "--reporter=json", "-t", self._name_pattern(by_file), *by_file.keys()]
        else:  # jest
            cmd = [*base, "--json", "-t", self._name_pattern(by_file), *by_file.keys()]
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout)

        report = self._extract_json(proc.stdout)
        if report is None:
            raise HeddleError(
                "tests_failed_to_run",
                tokens.truncate(
                    f"{runner} could not run: " + _oneline(proc.stderr or proc.stdout), 60
                ),
            )
        fail = None
        for suite in report.get("testResults", []):
            for a in suite.get("assertionResults", []):
                if a.get("status") == "failed":
                    msg = _oneline(" ".join(a.get("failureMessages", []))) or "failed"
                    fail = (a.get("title", "test"), msg)
                    break
            if fail:
                break
        if fail:
            name, detail = fail
            return (False, tokens.truncate(f"{name}: {detail}", SUMMARY_MAX_TOKENS))
        return (True, "")

    def _extract_json(self, out: str) -> dict | None:
        start, end = out.find("{"), out.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            return json.loads(out[start: end + 1])
        except json.JSONDecodeError:
            return None
