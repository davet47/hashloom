"""The Java adapter: a javac-tree hash helper plus the project's own Maven or
Gradle as the test runner.

Hashing shells out to `javahash/JavaHash.java` via Java's single-file source
launcher (JDK >= 11), so hashloom writes no hand-rolled Java parser — the same
stdlib-only stance as the Go adapter. The runner is auto-detected from the
project: `pom.xml` routes to Maven, `build.gradle`/`build.gradle.kts` to Gradle,
and a committed `mvnw`/`gradlew` wrapper is preferred over the PATH binary so a
project verifies against its own build, the stance the TypeScript adapter takes
with the project's own `typescript`.

Both runners are told not to fail modules/subprojects where the test filter
matches nothing, so a multi-module reactor behaves like `go test -run` over
packages: unrelated modules are silently green, only the targeted tests decide.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

from .. import tokens
from ..config import load_config
from ..errors import HashloomError
from . import SUMMARY_MAX_TOKENS

_JAVAHASH = Path(__file__).parent / "javahash" / "JavaHash.java"
_GRADLE_INIT = Path(__file__).parent / "hashloom-init.gradle"
_JAVA_VERSION = re.compile(r"^\S+\s+(\S+)")  # `openjdk 21.0.3 2024-04-16 LTS`
# a surefire failure line naming a test: `[ERROR]   CalcTest.totalSums:12 expected: <3>...`
_MVN_FAIL_LINE = re.compile(r"\[ERROR\]\s+([A-Za-z_$][\w$]*\.[\w$]+.*)")
_MVN_COUNTS = re.compile(r"Tests run: \d+, Failures: (\d+), Errors: (\d+)")
# `CalcTest > totalSums() FAILED`, including @Nested / parameterized / @DisplayName
# segments with spaces; build lines (`> Task :test FAILED`) start with `> ` and never match
_GRADLE_FAIL_LINE = re.compile(r"^\S+ > (.+) FAILED$")


def _oneline(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


class JavaAdapter:
    def __init__(self) -> None:
        self._java_cache: dict[tuple[str, str | None], str] = {}
        self._id_cache: dict[tuple[str, str | None], str] = {}
        self._home_cache: dict[str, str | None] = {}

    # -- toolchain ----------------------------------------------------------

    def resolve_toolchain(self, root: Path, override: str | None = None) -> str:
        return self._java(root, override)

    def _java(self, root: Path, override: str | None = None) -> str:
        key = (str(root), override)
        if key in self._java_cache:
            return self._java_cache[key]
        cand = override or load_config(root).get("java") or shutil.which("java")
        if not cand:
            raise HashloomError(
                "bad_toolchain",
                "no Java toolchain found (install a JDK, or set 'java' in .hashloom/config.json)",
            )
        try:
            subprocess.run([cand, "--version"], capture_output=True, check=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            raise HashloomError("bad_toolchain", f"'{cand}' is not a working Java toolchain (JDK >= 11)")
        self._java_cache[key] = cand
        return cand

    def toolchain_identity(self, root: Path, override: str | None = None) -> str:
        key = (str(root), override)
        if key in self._id_cache:
            return self._id_cache[key]
        java = self._java(root, override)
        try:
            proc = subprocess.run(
                [java, "--version"], capture_output=True, text=True, check=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            raise HashloomError("bad_toolchain", f"could not read the Java version from '{java}'")
        first = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
        m = _JAVA_VERSION.match(first)
        # version only (drop vendor and build date) so cross-OS/vendor greens share
        ident = f"java {m.group(1)}" if m else f"java {_oneline(first or proc.stdout)}"
        self._id_cache[key] = ident
        return ident

    def _java_home(self, java: str) -> str | None:
        """The resolved JVM's own java.home, so Maven/Gradle run the same JDK
        the verification key names (they pick their JVM from JAVA_HOME)."""
        if java in self._home_cache:
            return self._home_cache[java]
        home = None
        try:
            proc = subprocess.run(
                [java, "-XshowSettings:properties", "-version"],
                capture_output=True, text=True, timeout=30,
            )
            for line in proc.stderr.splitlines():
                k, _, v = line.partition("=")
                if k.strip() == "java.home" and v.strip():
                    home = v.strip()
                    break
        except (OSError, subprocess.SubprocessError):
            home = None
        self._home_cache[java] = home
        return home

    # -- hashing (via the JavaHash helper) -----------------------------------

    def impl_hash(self, root: Path, impl: str, contract: str | None = None) -> str:
        path_str, _, qual = impl.partition("::")
        return self._hash_def(root, path_str, qual, contract=contract)

    def _hash_def(self, root: Path, path_str: str, qual: str, contract: str | None = None) -> str:
        java = self._java(root)
        proc = subprocess.run(
            [java, str(_JAVAHASH), str(root / path_str), qual],
            capture_output=True, text=True, timeout=120,
        )
        kind, _, rest = proc.stdout.strip().partition(" ")
        if kind == "hash":
            return rest
        if kind == "not_found":
            raise HashloomError("impl_not_found", rest, contract=contract)
        if kind == "syntax":
            raise HashloomError("impl_syntax_error", rest, contract=contract)
        if kind == "notoolchain":
            raise HashloomError("bad_toolchain", rest, contract=contract)
        # the helper itself could not run (JRE-only java, helper error, ...)
        raise HashloomError(
            "tests_failed_to_run",
            tokens.truncate("java ast helper failed: " + _oneline(proc.stderr or proc.stdout), 60),
        )

    def test_source_hash(self, root: Path, node_ids: list[str]) -> str:
        parts = []
        for nid in sorted(node_ids):
            path_str, _, test = nid.partition("::")
            h = None
            if path_str and test:
                # a Java test node id names a method (dotted for @Nested
                # classes); its top-level class is the file's stem
                qual = f"{Path(path_str).stem}.{test}"
                try:
                    h = self._hash_def(root, path_str, qual)
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

    # -- running tests (auto-detected Maven or Gradle) ------------------------

    def run_tests(
        self, root: Path, node_ids: list[str], toolchain: str, timeout: int | float
    ) -> tuple[bool, str]:
        by_class = self._by_class(node_ids)
        env = os.environ.copy()
        home = self._java_home(toolchain)
        if home:
            env["JAVA_HOME"] = home

        runner, base = self._detect_runner(root)
        if runner == "maven":
            cmd = [
                *base, "--batch-mode", "-q", f"-Dtest={self._maven_spec(by_class)}",
                # unrelated reactor modules with no matching tests stay green,
                # like `go test -run` over packages
                "-Dsurefire.failIfNoSpecifiedTests=false", "-DfailIfNoTests=false",
                "test",
            ]
            return self._parse_maven(self._run(cmd, root, env, timeout, "mvn"))
        cmd = [
            *base, "--console=plain", "--no-daemon",
            "--init-script", str(_GRADLE_INIT), "test",
        ]
        for pattern in self._gradle_patterns(by_class):
            cmd += ["--tests", pattern]
        return self._parse_gradle(self._run(cmd, root, env, timeout, "gradle"))

    def _run(
        self, cmd: list[str], root: Path, env: dict, timeout: int | float, runner: str
    ) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                cmd, cwd=root, env=env, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            raise HashloomError(
                "tests_failed_to_run", f"{runner} test timed out after {timeout:g}s"
            )

    def _by_class(self, node_ids: list[str]) -> dict[str, list[str]]:
        # a Java test node id is "src/test/java/CalcTest.java::methodName", or
        # "...::Inner.methodName" for @Nested classes; the top-level class is
        # the file's stem (Java requires the names to match) and runners match
        # nested classes by their runtime name, Outer$Inner
        by_class: dict[str, list[str]] = {}
        for nid in node_ids:
            path_str, _, test = nid.partition("::")
            nested, _, method = test.rpartition(".")
            cls = Path(path_str).stem
            if nested:
                cls += "$" + nested.replace(".", "$")
            by_class.setdefault(cls, []).append(method)
        return by_class

    def _detect_runner(self, root: Path) -> tuple[str, list[str]]:
        """Maven if pom.xml, Gradle if build.gradle(.kts); wrappers preferred."""
        if (root / "pom.xml").is_file():
            mvnw = root / "mvnw"
            if mvnw.is_file() and os.access(mvnw, os.X_OK):
                return ("maven", [str(mvnw)])
            mvn = shutil.which("mvn")
            if mvn:
                return ("maven", [mvn])
            raise HashloomError(
                "bad_toolchain", "pom.xml found but no mvn on PATH (install Maven or commit the mvnw wrapper)"
            )
        if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
            gradlew = root / "gradlew"
            if gradlew.is_file() and os.access(gradlew, os.X_OK):
                return ("gradle", [str(gradlew)])
            gradle = shutil.which("gradle")
            if gradle:
                return ("gradle", [gradle])
            raise HashloomError(
                "bad_toolchain",
                "build.gradle found but no gradle on PATH (install Gradle or commit the gradlew wrapper)",
            )
        raise HashloomError(
            "bad_toolchain", "no pom.xml or build.gradle found — Java tests need Maven or Gradle"
        )

    def _maven_spec(self, by_class: dict[str, list[str]]) -> str:
        # surefire's -Dtest grammar: Class#methodA+methodB,OtherClass#methodC
        return ",".join(f"{cls}#{'+'.join(tests)}" for cls, tests in sorted(by_class.items()))

    def _gradle_patterns(self, by_class: dict[str, list[str]]) -> list[str]:
        # --tests matches fully-qualified names; the leading * absorbs the package
        return [f"*{cls}.{t}" for cls, tests in sorted(by_class.items()) for t in tests]

    def _parse_maven(self, proc: subprocess.CompletedProcess) -> tuple[bool, str]:
        if proc.returncode == 0:
            return (True, "")
        out = proc.stdout + "\n" + proc.stderr
        counts = [m for m in _MVN_COUNTS.finditer(out) if m.group(1) != "0" or m.group(2) != "0"]
        # non-zero exit with no failed-test counts means the build could not run
        if not counts:
            first_error = next(
                (l.strip() for l in out.splitlines() if l.strip().startswith("[ERROR]")), out
            )
            raise HashloomError(
                "tests_failed_to_run",
                tokens.truncate("mvn test could not run: " + _oneline(first_error), 60),
            )
        matches = []
        for line in out.splitlines():
            m = _MVN_FAIL_LINE.search(line)
            if m and not m.group(1).startswith(("Tests run", "Failures:", "Errors:")):
                matches.append(m.group(1))
        if matches:
            # prefer the Results-section line (it carries expected/actual) over
            # the per-test `Time elapsed ... <<< FAILURE!` progress line
            best = next((s for s in matches if "<<<" not in s), matches[0])
            return (False, tokens.truncate(_oneline(best), SUMMARY_MAX_TOKENS))
        return (False, tokens.truncate("tests failed", SUMMARY_MAX_TOKENS))

    def _parse_gradle(self, proc: subprocess.CompletedProcess) -> tuple[bool, str]:
        if proc.returncode == 0:
            return (True, "")
        lines = (proc.stdout + "\n" + proc.stderr).splitlines()
        for i, line in enumerate(lines):
            m = _GRADLE_FAIL_LINE.match(line.strip())
            if m:
                detail = next((l.strip() for l in lines[i + 1: i + 4] if l.strip()), "failed")
                return (False, tokens.truncate(f"{m.group(1)}: {_oneline(detail)}", SUMMARY_MAX_TOKENS))
        raise HashloomError(
            "tests_failed_to_run",
            tokens.truncate(
                "gradle test could not run: " + _oneline(proc.stderr or proc.stdout), 60
            ),
        )
