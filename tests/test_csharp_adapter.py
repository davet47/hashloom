"""The C# adapter end to end: Roslyn token-stream impl hashing (stable under
formatting, sensitive to behaviour) and the `dotnet test` runner via the verify
flow. Filter mapping and output parsing are unit-tested without any SDK, so
part of this file always runs; the hash tests need a .NET SDK and the e2e tests
restore xunit from NuGet on top."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from hashloom import api
from hashloom.errors import HashloomError
from hashloom.indexer import index
from hashloom.langs import adapter_for
from hashloom.langs.csharp import CSharpAdapter
from hashloom.project import db_path, init_project
from hashloom.store import SqliteStore


def _sdk_major() -> int | None:
    """The installed .NET SDK's major version, or None without a working SDK
    (a runtime-only install makes `dotnet --version` exit nonzero)."""
    exe = shutil.which("dotnet")
    if exe is None:
        return None
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip().split(".")[0])
    except ValueError:
        return None


_MAJOR = _sdk_major()
needs_dotnet = pytest.mark.skipif(_MAJOR is None, reason=".NET SDK not installed")

_IMPL = "src/Calc.cs::Calc.Total"
_GOOD = (
    "public class Calc {\n"
    "    public static int Total(int[] xs) {\n"
    "        int s = 0;\n"
    "        foreach (var x in xs) {\n"
    "            s += x;\n"
    "        }\n"
    "        return s;\n"
    "    }\n"
    "}\n"
)


def _csharp_project(root: Path) -> None:
    init_project(root)
    (root / "calcproj.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk">\n'
        "  <PropertyGroup>\n"
        f"    <TargetFramework>net{_MAJOR or 9}.0</TargetFramework>\n"
        "    <Nullable>disable</Nullable>\n"
        "    <IsPackable>false</IsPackable>\n"
        "  </PropertyGroup>\n"
        "  <ItemGroup>\n"
        '    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />\n'
        '    <PackageReference Include="xunit" Version="2.9.2" />\n'
        '    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2" />\n'
        "  </ItemGroup>\n"
        "</Project>\n"
    )
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "Calc.cs").write_text(_GOOD)
    (root / "tests" / "CalcTests.cs").write_text(
        "using Xunit;\n\n"
        "public class CalcTests {\n"
        "    [Fact]\n"
        "    public void TotalSums() {\n"
        "        Assert.Equal(3, Calc.Total(new[] {1, 2}));\n"
        "    }\n"
        "}\n"
    )
    (root / "contracts" / "calc.yaml").write_text(textwrap.dedent("""
        name: calc
        signature: "public static int Total(int[] xs)"
        tests: [tests/CalcTests.cs::TotalSums]
        impl: src/Calc.cs::Calc.Total
    """).strip() + "\n")


# -- hashing (needs an SDK, no runner) ----------------------------------------


@needs_dotnet
def test_csharp_impl_hash_stable_under_formatting_but_not_behaviour(tmp_path):
    _csharp_project(tmp_path)
    a = adapter_for(_IMPL)
    base = a.impl_hash(tmp_path, _IMPL)
    # reformat + comment + xml-doc, same behaviour -> same hash
    (tmp_path / "src" / "Calc.cs").write_text(
        "public class Calc {\n"
        "    /// <summary>Sums xs.</summary>\n"
        "    public static int Total(int[] xs) {\n"
        "        int s = 0;\n"
        "        foreach (var x in xs) { s += x; } // reflowed\n"
        "        return s;\n"
        "    }\n"
        "}\n"
    )
    assert a.impl_hash(tmp_path, _IMPL) == base
    # behaviour change (+= -> -=) -> different hash
    (tmp_path / "src" / "Calc.cs").write_text(_GOOD.replace("s += x", "s -= x"))
    assert a.impl_hash(tmp_path, _IMPL) != base


@needs_dotnet
def test_csharp_surrounding_members_do_not_change_the_hash(tmp_path):
    _csharp_project(tmp_path)
    a = adapter_for(_IMPL)
    base = a.impl_hash(tmp_path, _IMPL)
    (tmp_path / "src" / "Calc.cs").write_text(
        _GOOD.replace("}\n}\n", "}\n\n    public static int Unrelated() {\n        return 7;\n    }\n}\n")
    )
    assert a.impl_hash(tmp_path, _IMPL) == base
    # but the whole-class hash does see the new member
    assert a.impl_hash(tmp_path, "src/Calc.cs::Calc") != a.impl_hash(tmp_path, _IMPL)


@needs_dotnet
def test_csharp_missing_def_and_file_raise_impl_not_found(tmp_path):
    _csharp_project(tmp_path)
    a = adapter_for(_IMPL)
    with pytest.raises(HashloomError) as e:
        a.impl_hash(tmp_path, "src/Calc.cs::Calc.Nope")
    assert e.value.code == "impl_not_found"
    with pytest.raises(HashloomError) as e:
        a.impl_hash(tmp_path, "src/Missing.cs::Calc.Total")
    assert e.value.code == "impl_not_found"


@needs_dotnet
def test_csharp_impl_syntax_error(tmp_path):
    _csharp_project(tmp_path)
    (tmp_path / "src" / "Calc.cs").write_text("public class Calc { public static int Total( {\n")
    with pytest.raises(HashloomError) as e:
        adapter_for(_IMPL).impl_hash(tmp_path, _IMPL)
    assert e.value.code == "impl_syntax_error"


@needs_dotnet
def test_csharp_toolchain_identity_is_version_only_for_manifestless_root(tmp_path):
    ident = adapter_for(_IMPL).toolchain_identity(tmp_path)
    assert ident.startswith("dotnet ")
    assert ident.split()[1][0].isdigit()
    assert " deps " not in ident


@needs_dotnet
def test_csharp_identity_gains_dep_suffix_from_lockfile(tmp_path):
    (tmp_path / "packages.lock.json").write_text('{"version": 1}\n')
    ident = adapter_for(_IMPL).toolchain_identity(tmp_path)
    assert " deps packages.lock.json=" in ident


@needs_dotnet
def test_csharp_helper_recompiles_into_a_fresh_cache(tmp_path, monkeypatch):
    # a fresh XDG_CACHE_HOME forces the one-time csc compile of the helper,
    # and the hash must not depend on which compiled copy produced it
    _csharp_project(tmp_path)
    baseline = adapter_for(_IMPL).impl_hash(tmp_path, _IMPL)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    a = CSharpAdapter()  # fresh instance: nothing memoised
    assert a.impl_hash(tmp_path, _IMPL) == baseline
    assert len(list((tmp_path / "cache" / "hashloom" / "cshash").glob("*/CsHash.dll"))) == 1


# -- toolchain + discovery error paths (no SDK needed) -------------------------


def test_csharp_no_toolchain_is_a_structured_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(HashloomError) as e:
        CSharpAdapter().resolve_toolchain(tmp_path)
    assert e.value.code == "bad_toolchain"


def test_csharp_broken_override_is_a_structured_refusal(tmp_path):
    false = shutil.which("false")
    with pytest.raises(HashloomError) as e:
        CSharpAdapter().resolve_toolchain(tmp_path, override=false)
    assert e.value.code == "bad_toolchain"


def test_csharp_sdk_and_framework_discovery(tmp_path, monkeypatch):
    a = CSharpAdapter()

    def fake_list(dotnet, root, flag):
        if flag == "--list-sdks":
            out = "8.0.100 [/dn/sdk]\n9.0.303 [/dn/sdk]\n"
        else:
            out = (
                "Microsoft.AspNetCore.App 9.0.7 [/dn/shared/Microsoft.AspNetCore.App]\n"
                "Microsoft.NETCore.App 8.0.10 [/dn/shared/Microsoft.NETCore.App]\n"
                "Microsoft.NETCore.App 9.0.7 [/dn/shared/Microsoft.NETCore.App]\n"
                "Microsoft.NETCore.App 9.0.2 [/dn/shared/Microsoft.NETCore.App]\n"
            )
        return subprocess.CompletedProcess([], 0, out, "")

    monkeypatch.setattr(a, "_list", fake_list)
    assert a._sdk_dir("dotnet", tmp_path, "9.0.303") == Path("/dn/sdk/9.0.303")
    # newest shared framework of the SDK's own major, never another major/pack
    assert a._framework_dir("dotnet", tmp_path, "9.0.303") == Path(
        "/dn/shared/Microsoft.NETCore.App/9.0.7"
    )
    with pytest.raises(HashloomError) as e:
        a._sdk_dir("dotnet", tmp_path, "7.0.100")
    assert e.value.code == "bad_toolchain"
    with pytest.raises(HashloomError) as e:
        a._framework_dir("dotnet", tmp_path, "10.0.100")
    assert e.value.code == "bad_toolchain"


def test_csharp_impl_source_missing_file_is_none(tmp_path):
    assert CSharpAdapter().impl_source(tmp_path, "src/Missing.cs::X") is None


# -- filter mapping + output parsing (no SDK needed) ---------------------------


def test_csharp_project_detection(tmp_path):
    a = CSharpAdapter()
    with pytest.raises(HashloomError) as e:
        a.run_tests(tmp_path, ["tests/CalcTests.cs::TotalSums"], "dotnet", 60)
    assert e.value.code == "bad_toolchain"
    for marker in ("app.sln", "app.slnx", "app.csproj"):
        (tmp_path / marker).write_text("")
        assert a._has_project(tmp_path)
        (tmp_path / marker).unlink()


def test_csharp_filter_mapping():
    a = CSharpAdapter()
    assert a._filter(
        [
            "tests/CalcTests.cs::TotalSums",
            "tests/CalcTests.cs::Inner.Nested",
            "t/OtherTests.cs::Works",
        ]
    ) == (
        # sorted node ids; nested classes use the runtime `Outer+Inner` spelling
        "FullyQualifiedName~OtherTests.Works"
        "|FullyQualifiedName~CalcTests+Inner.Nested"
        "|FullyQualifiedName~CalcTests.TotalSums"
    )


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_csharp_test_output_parsing():
    a = CSharpAdapter()
    assert a._parse_test(_proc(0)) == (True, "")
    out = (
        "  Failed CalcTests.TotalSums [< 1 ms]\n"
        "  Error Message:\n"
        "   Assert.Equal() Failure: Values differ\n"
        "Expected: 3\n"
        "Actual:   4\n"
        "  Stack Trace:\n"
        "     at CalcTests.TotalSums()\n"
        "\n"
        "Failed!  - Failed:     1, Passed:     0, Skipped:     0, Total:     1, Duration: < 1 ms\n"
    )
    ok, summary = a._parse_test(_proc(1, out))
    assert not ok and "TotalSums" in summary and "Assert.Equal" in summary
    # the `Failed!` summary line alone never reads as a test name
    with pytest.raises(HashloomError) as e:
        a._parse_test(
            _proc(1, "/x/Calc.cs(3,16): error CS0103: The name 'Nope' does not exist\n")
        )
    assert e.value.code == "tests_failed_to_run"


def test_csharp_nested_failure_line_parses():
    a = CSharpAdapter()
    out = "  Failed CalcTests+Inner.Nested [2 ms]\n  Error Message:\n   boom\n"
    ok, summary = a._parse_test(_proc(1, out))
    assert not ok and "Inner.Nested" in summary and "boom" in summary
    # a failure line with no Error Message block still summarises
    ok, summary = a._parse_test(_proc(1, "  Failed CalcTests.TotalSums [1 ms]\n"))
    assert not ok and summary == "CalcTests.TotalSums: failed"


# -- end to end via dotnet test (restores xunit from NuGet) --------------------


@needs_dotnet
def test_csharp_verify_pass_then_cached(tmp_path):
    _csharp_project(tmp_path)
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        assert api.verify(tmp_path, store, ["calc"])["results"][0]["status"] == "pass"
        assert api.verify(tmp_path, store, ["calc"])["results"][0]["status"] == "cached-pass"
        # the impl source blob was stored (serve weft)
        assert "public static int Total" in store.get_blob(store.get_impl("calc")["blob_hash"])
    finally:
        store.close()


@needs_dotnet
def test_csharp_verify_fail_has_summary(tmp_path):
    _csharp_project(tmp_path)
    (tmp_path / "src" / "Calc.cs").write_text(
        _GOOD.replace("return s", "return s + 1")  # compiles, wrong result
    )
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        r = api.verify(tmp_path, store, ["calc"])["results"][0]
        assert r["status"] == "fail"
        assert "TotalSums" in r.get("summary", "")
    finally:
        store.close()


@needs_dotnet
def test_csharp_build_error_is_a_runner_error(tmp_path):
    _csharp_project(tmp_path)
    # parses fine, but references an undefined name: fails at build time
    (tmp_path / "src" / "Calc.cs").write_text(
        "public class Calc {\n    public static int Total(int[] xs) {\n        return Nope(xs);\n    }\n}\n"
    )
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        r = api.verify(tmp_path, store, ["calc"])["results"][0]
        assert r["status"] == "error"
        assert r["error"]["code"] == "tests_failed_to_run"
    finally:
        store.close()
