"""The Java adapter end to end: javac-tree impl hashing (stable under formatting,
sensitive to behaviour) and the auto-detected Maven/Gradle runner via the verify
flow. Runner detection and argument mapping are unit-tested without any JDK, so
part of this file always runs; the hash tests need a JDK and the e2e tests need
Maven on top."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from heddle import api
from heddle.errors import HeddleError
from heddle.indexer import index
from heddle.langs import adapter_for
from heddle.langs.java import JavaAdapter
from heddle.project import db_path, init_project
from heddle.store import SqliteStore


def _has_jdk() -> bool:
    """A JDK (not the macOS /usr/bin/java stub or a bare JRE) that can run
    the single-file hash helper. Both binaries are executed, not just found:
    the macOS stubs exist even with no runtime installed and exit nonzero."""
    for tool, flag in (("java", "--version"), ("javac", "-version")):
        exe = shutil.which(tool)
        if exe is None:
            return False
        try:
            if subprocess.run([exe, flag], capture_output=True, timeout=30).returncode != 0:
                return False
        except (OSError, subprocess.SubprocessError):
            return False
    return True


needs_jdk = pytest.mark.skipif(not _has_jdk(), reason="JDK not installed")
needs_maven = pytest.mark.skipif(
    not _has_jdk() or shutil.which("mvn") is None, reason="JDK + Maven not installed"
)

_IMPL = "src/main/java/Calc.java::Calc.total"
_GOOD = (
    "public class Calc {\n"
    "    static int total(int[] xs) {\n"
    "        int s = 0;\n"
    "        for (int x : xs) {\n"
    "            s += x;\n"
    "        }\n"
    "        return s;\n"
    "    }\n"
    "}\n"
)

_POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>heddle.fixture</groupId>
  <artifactId>calcproj</artifactId>
  <version>0.0.1</version>
  <properties>
    <maven.compiler.release>11</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.10.2</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
        <version>3.2.5</version>
      </plugin>
    </plugins>
  </build>
</project>
"""


def _java_project(root: Path) -> None:
    init_project(root)
    (root / "pom.xml").write_text(_POM)
    (root / "src" / "main" / "java").mkdir(parents=True)
    (root / "src" / "test" / "java").mkdir(parents=True)
    (root / "src" / "main" / "java" / "Calc.java").write_text(_GOOD)
    (root / "src" / "test" / "java" / "CalcTest.java").write_text(
        "import org.junit.jupiter.api.Test;\n"
        "import static org.junit.jupiter.api.Assertions.assertEquals;\n\n"
        "public class CalcTest {\n"
        "    @Test\n"
        "    void totalSums() {\n"
        "        assertEquals(3, Calc.total(new int[]{1, 2}));\n"
        "    }\n"
        "}\n"
    )
    (root / "contracts" / "calc.yaml").write_text(textwrap.dedent("""
        name: calc
        signature: "static int total(int[] xs)"
        tests: [src/test/java/CalcTest.java::totalSums]
        impl: src/main/java/Calc.java::Calc.total
    """).strip() + "\n")


# -- hashing (needs a JDK, no runner) ----------------------------------------


@needs_jdk
def test_java_impl_hash_stable_under_formatting_but_not_behaviour(tmp_path):
    _java_project(tmp_path)
    a = adapter_for(_IMPL)
    base = a.impl_hash(tmp_path, _IMPL)
    # reformat + comment + javadoc, same behaviour -> same hash
    (tmp_path / "src" / "main" / "java" / "Calc.java").write_text(
        "public class Calc {\n"
        "    /** Sums xs. */\n"
        "    static int total(int[] xs) {\n"
        "        int s = 0;\n"
        "        for (int x : xs) { s += x; } // reflowed\n"
        "        return s;\n"
        "    }\n"
        "}\n"
    )
    assert a.impl_hash(tmp_path, _IMPL) == base
    # behaviour change (+= -> -=) -> different hash
    (tmp_path / "src" / "main" / "java" / "Calc.java").write_text(_GOOD.replace("s += x", "s -= x"))
    assert a.impl_hash(tmp_path, _IMPL) != base


@needs_jdk
def test_java_surrounding_members_do_not_change_the_hash(tmp_path):
    _java_project(tmp_path)
    a = adapter_for(_IMPL)
    base = a.impl_hash(tmp_path, _IMPL)
    (tmp_path / "src" / "main" / "java" / "Calc.java").write_text(
        _GOOD.replace("}\n}\n", "}\n\n    static int unrelated() {\n        return 7;\n    }\n}\n")
    )
    assert a.impl_hash(tmp_path, _IMPL) == base
    # but the whole-class hash does see the new member
    assert a.impl_hash(tmp_path, "src/main/java/Calc.java::Calc") != a.impl_hash(tmp_path, _IMPL)


@needs_jdk
def test_java_missing_def_and_file_raise_impl_not_found(tmp_path):
    _java_project(tmp_path)
    a = adapter_for(_IMPL)
    with pytest.raises(HeddleError) as e:
        a.impl_hash(tmp_path, "src/main/java/Calc.java::Calc.nope")
    assert e.value.code == "impl_not_found"
    with pytest.raises(HeddleError) as e:
        a.impl_hash(tmp_path, "src/main/java/Missing.java::Calc.total")
    assert e.value.code == "impl_not_found"


@needs_jdk
def test_java_impl_syntax_error(tmp_path):
    _java_project(tmp_path)
    (tmp_path / "src" / "main" / "java" / "Calc.java").write_text("public class Calc { static int total( {\n")
    with pytest.raises(HeddleError) as e:
        adapter_for(_IMPL).impl_hash(tmp_path, _IMPL)
    assert e.value.code == "impl_syntax_error"


@needs_jdk
def test_java_toolchain_identity_is_version_only(tmp_path):
    ident = adapter_for(_IMPL).toolchain_identity(tmp_path)
    assert ident.startswith("java ")
    assert ident.split()[1][0].isdigit()


# -- runner detection + argument mapping (no JDK needed) ----------------------


def test_java_runner_detection(tmp_path, monkeypatch):
    a = JavaAdapter()
    # no manifest at all -> structured refusal
    with pytest.raises(HeddleError) as e:
        a._detect_runner(tmp_path)
    assert e.value.code == "bad_toolchain"

    (tmp_path / "pom.xml").write_text("<project/>")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert a._detect_runner(tmp_path) == ("maven", ["/usr/bin/mvn"])

    # a committed executable wrapper wins over the PATH binary
    mvnw = tmp_path / "mvnw"
    mvnw.write_text("#!/bin/sh\n")
    mvnw.chmod(0o755)
    assert a._detect_runner(tmp_path) == ("maven", [str(mvnw)])

    # manifest present but nothing to run it with -> structured refusal
    monkeypatch.setattr(shutil, "which", lambda name: None)
    (tmp_path / "mvnw").unlink()
    with pytest.raises(HeddleError) as e:
        a._detect_runner(tmp_path)
    assert e.value.code == "bad_toolchain"


def test_java_gradle_detection(tmp_path, monkeypatch):
    a = JavaAdapter()
    (tmp_path / "build.gradle").write_text("")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert a._detect_runner(tmp_path) == ("gradle", ["/usr/bin/gradle"])
    # pom.xml wins when both manifests exist
    (tmp_path / "pom.xml").write_text("<project/>")
    assert a._detect_runner(tmp_path)[0] == "maven"


def test_java_runner_argument_mapping():
    a = JavaAdapter()
    by_class = {"CalcTest": ["totalSums", "totalEmpty"], "OtherTest": ["works"]}
    assert a._maven_spec(by_class) == "CalcTest#totalSums+totalEmpty,OtherTest#works"
    assert a._gradle_patterns(by_class) == [
        "*CalcTest.totalSums",
        "*CalcTest.totalEmpty",
        "*OtherTest.works",
    ]


def test_java_nested_class_node_ids_map_to_runtime_names():
    a = JavaAdapter()
    assert a._by_class(
        [
            "src/test/java/CalcTest.java::totalSums",
            "src/test/java/CalcTest.java::Inner.nested",
            "t/OtherTest.java::works",
        ]
    ) == {"CalcTest": ["totalSums"], "CalcTest$Inner": ["nested"], "OtherTest": ["works"]}


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_java_maven_output_parsing():
    a = JavaAdapter()
    assert a._parse_maven(_proc(0)) == (True, "")
    out = (
        "[ERROR] CalcTest.totalSums -- Time elapsed: 0.016 s <<< FAILURE!\n"
        "[ERROR] Tests run: 1, Failures: 1, Errors: 0, Skipped: 0\n"
        "[ERROR] Failures:\n"
        "[ERROR]   CalcTest.totalSums:7 expected: <3> but was: <4>\n"
    )
    ok, summary = a._parse_maven(_proc(1, out))
    # the Results-section line wins over the `<<< FAILURE!` progress line
    assert not ok and "totalSums" in summary and "expected" in summary
    with pytest.raises(HeddleError) as e:
        a._parse_maven(_proc(1, "[ERROR] COMPILATION ERROR :\n[ERROR] Calc.java:[3,16] cannot find symbol\n"))
    assert e.value.code == "tests_failed_to_run"


def test_java_gradle_output_parsing():
    a = JavaAdapter()
    assert a._parse_gradle(_proc(0)) == (True, "")
    detail = "\n    org.opentest4j.AssertionFailedError: expected: <3> but was: <4>\n"
    for line in (
        "CalcTest > totalSums() FAILED",  # plain JUnit 5
        "CalcTest > InnerTests > nestedSum() FAILED",  # @Nested
        "CalcTest > sums(int, int) > [1] 1, 2 FAILED",  # @ParameterizedTest
        "CalcTest > sums correctly FAILED",  # @DisplayName
    ):
        ok, summary = a._parse_gradle(_proc(1, line + detail))
        assert not ok and "expected" in summary, line
    # a compile error has no test-failure line: a runner error, not a fail
    with pytest.raises(HeddleError) as e:
        a._parse_gradle(_proc(1, "> Task :compileTestJava FAILED\nBUILD FAILED in 1s\n"))
    assert e.value.code == "tests_failed_to_run"


# -- end to end via Maven (CI installs a JDK; Maven ships on the runner) ------


@needs_maven
def test_java_verify_pass_then_cached(tmp_path):
    _java_project(tmp_path)
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        assert api.verify(tmp_path, store, ["calc"])["results"][0]["status"] == "pass"
        assert api.verify(tmp_path, store, ["calc"])["results"][0]["status"] == "cached-pass"
        # the impl source blob was stored (serve weft)
        assert "static int total" in store.get_blob(store.get_impl("calc")["blob_hash"])
    finally:
        store.close()


@needs_maven
def test_java_verify_fail_has_summary(tmp_path):
    _java_project(tmp_path)
    (tmp_path / "src" / "main" / "java" / "Calc.java").write_text(
        _GOOD.replace("return s", "return s + 1")  # compiles, wrong result
    )
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        r = api.verify(tmp_path, store, ["calc"])["results"][0]
        assert r["status"] == "fail"
        assert "totalSums" in r.get("summary", "")
    finally:
        store.close()


@needs_maven
def test_java_build_error_is_a_runner_error(tmp_path):
    _java_project(tmp_path)
    # parses fine, but references an undefined name: fails at test-compile time
    (tmp_path / "src" / "main" / "java" / "Calc.java").write_text(
        "public class Calc {\n    static int total(int[] xs) {\n        return nope(xs);\n    }\n}\n"
    )
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        r = api.verify(tmp_path, store, ["calc"])["results"][0]
        assert r["status"] == "error"
        assert r["error"]["code"] == "tests_failed_to_run"
    finally:
        store.close()
