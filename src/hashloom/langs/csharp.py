"""The C# adapter: a Roslyn token-stream hash helper plus `dotnet test` as the
test runner.

Hashing shells out to `cshash/CsHash.cs`, compiled once per SDK version with
the SDK's *own* `csc` against the SDK's own bundled `Microsoft.CodeAnalysis*`
assemblies — no NuGet package, no network, the same no-hand-rolled-parser
stance as the Go and Java adapters (the .NET SDK has no single-file source
launcher before .NET 10, so the one-time compile stands in for Java's). The
compiled helper lands in the user cache dir, keyed by SDK version and helper
source, so the cost is paid once per machine per SDK.

The runner is `dotnet test` on the project root (any `.sln`/`.slnx`/`.csproj`
there — xUnit, NUnit, and MSTest all ride the same VSTest filter grammar).
A C# test node id is "tests/CalcTests.cs::TotalSums": the top-level class is
the file's stem (the ecosystem's file-per-class convention, the same reading
the Java adapter uses) and "Inner.Method" segments map to the runtime
`Outer+Inner` spelling. Filters use the `FullyQualifiedName~` contains-match,
so namespaces never appear in node ids.
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
from .deps import dep_suffix

# the opt-in NuGet lockfile (the resolved set) wins; central package management
# is the declared-manifest fallback grain. Per-project *.csproj files carry no
# fixed root name, so they stay out — absence keeps the version-only identity
_DEP_SOURCES = ("packages.lock.json", "Directory.Packages.props")

_CSHASH = Path(__file__).parent / "cshash" / "CsHash.cs"

# framework facades the helper compile references, resolved from the shared
# framework dir by name (missing ones are skipped — names vary across majors)
_FRAMEWORK_REFS = (
    # the facades type-forward into System.Private.CoreLib, so csc needs it
    # referenced to resolve the forwards (an implementation-assembly compile)
    "System.Private.CoreLib.dll",
    "netstandard.dll",
    "System.Runtime.dll",
    "System.Console.dll",
    "System.Linq.dll",
    "System.Collections.dll",
    "System.Collections.Immutable.dll",
    "System.Memory.dll",
    "System.Security.Cryptography.dll",
    "System.Security.Cryptography.Algorithms.dll",
    "System.Text.Encoding.Extensions.dll",
    "System.Runtime.Extensions.dll",
    "System.IO.dll",
)

# `9.0.303 [/usr/local/share/dotnet/sdk]` (dotnet --list-sdks)
_SDK_LINE = re.compile(r"^(\S+)\s+\[(.+)\]\s*$")
# `Microsoft.NETCore.App 9.0.7 [/usr/local/share/dotnet/shared/...]`
_RUNTIME_LINE = re.compile(r"^Microsoft\.NETCore\.App\s+(\S+)\s+\[(.+)\]\s*$")
# `  Failed CalcTests.TotalSums [12 ms]` — never the `Failed!` summary line
_FAIL_LINE = re.compile(r"^\s*Failed ([\w.+$]\S*)(?:\s+\[.*\])?$")


def _oneline(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _env() -> dict:
    env = os.environ.copy()
    # keep first-run banners and telemetry chatter out of parsed output
    env["DOTNET_NOLOGO"] = "1"
    env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    env["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1"
    return env


def _semver(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in v.partition("-")[0].split("."))
    except ValueError:
        return (0,)


class CSharpAdapter:
    def __init__(self) -> None:
        self._dotnet_cache: dict[tuple[str, str | None], str] = {}
        self._ver_cache: dict[tuple[str, str | None], str] = {}
        self._helper_cache: dict[tuple[str, str], Path] = {}

    # -- toolchain ----------------------------------------------------------

    def resolve_toolchain(self, root: Path, override: str | None = None) -> str:
        return self._dotnet(root, override)

    def _dotnet(self, root: Path, override: str | None = None) -> str:
        key = (str(root), override)
        if key in self._dotnet_cache:
            return self._dotnet_cache[key]
        cand = override or load_config(root).get("dotnet") or shutil.which("dotnet")
        if not cand:
            raise HashloomError(
                "bad_toolchain",
                "no .NET toolchain found (install the .NET SDK, or set 'dotnet' in .hashloom/config.json)",
            )
        # --version resolves the SDK (honouring global.json) and fails on a
        # runtime-only install — hashing and `dotnet test` both need the SDK
        try:
            subprocess.run(
                [cand, "--version"],
                cwd=root, env=_env(), capture_output=True, check=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            raise HashloomError("bad_toolchain", f"'{cand}' is not a working .NET SDK")
        self._dotnet_cache[key] = cand
        return cand

    def _sdk_version(self, root: Path, override: str | None = None) -> str:
        key = (str(root), override)
        if key not in self._ver_cache:
            dotnet = self._dotnet(root, override)
            try:
                proc = subprocess.run(
                    [dotnet, "--version"],
                    cwd=root, env=_env(), capture_output=True, text=True, check=True, timeout=30,
                )
            except (OSError, subprocess.SubprocessError):
                raise HashloomError("bad_toolchain", f"could not read the SDK version from '{dotnet}'")
            self._ver_cache[key] = proc.stdout.strip().splitlines()[-1].strip()
        return self._ver_cache[key]

    def toolchain_identity(self, root: Path, override: str | None = None) -> str:
        # SDK version only — never OS/arch — so cross-OS greens share
        return f"dotnet {self._sdk_version(root, override)}" + dep_suffix(root, _DEP_SOURCES)

    # -- the compiled hash helper --------------------------------------------

    def _helper(self, root: Path) -> tuple[str, Path]:
        """(dotnet, path to the compiled CsHash.dll), compiling on first use."""
        dotnet = self._dotnet(root)
        ver = self._sdk_version(root)
        key = (dotnet, ver)
        cached = self._helper_cache.get(key)
        if cached is not None and cached.is_file():
            return dotnet, cached
        src_tag = hashlib.sha256(_CSHASH.read_bytes()).hexdigest()[:12]
        cache_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
        out_dir = cache_home / "hashloom" / "cshash" / f"{ver}-{src_tag}"
        dll = out_dir / "CsHash.dll"
        if not dll.is_file():
            self._compile_helper(dotnet, root, ver, out_dir)
        self._helper_cache[key] = dll
        return dotnet, dll

    def _compile_helper(self, dotnet: str, root: Path, ver: str, out_dir: Path) -> None:
        bincore = self._sdk_dir(dotnet, root, ver) / "Roslyn" / "bincore"
        csc = bincore / "csc.dll"
        if not csc.is_file():
            raise HashloomError("bad_toolchain", f"no Roslyn compiler in the .NET SDK at {bincore}")
        roslyn = [bincore / "Microsoft.CodeAnalysis.dll", bincore / "Microsoft.CodeAnalysis.CSharp.dll"]
        fw = self._framework_dir(dotnet, root, ver)
        refs = roslyn + [fw / n for n in _FRAMEWORK_REFS if (fw / n).is_file()]

        # build in a scratch dir, then rename into place: concurrent compiles
        # of the same SDK version race benignly (first rename wins)
        tmp = out_dir.parent / f".build-{os.getpid()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(
                [
                    dotnet, str(csc), "-nologo", "-nostdlib", "-target:exe",
                    f"-out:{tmp / 'CsHash.dll'}",
                    *[f"-r:{r}" for r in refs], str(_CSHASH),
                ],
                env=_env(), capture_output=True, text=True, timeout=120,
            )
            if proc.returncode != 0:
                raise HashloomError(
                    "bad_toolchain",
                    tokens.truncate(
                        "could not compile the C# hash helper: "
                        + _oneline(proc.stdout or proc.stderr), 60,
                    ),
                )
            for dep in roslyn:
                shutil.copy2(dep, tmp / dep.name)
            # csc's own runtimeconfig requests exactly the framework its Roslyn
            # was built for, so reuse it for the helper
            cfg = bincore / "csc.runtimeconfig.json"
            if cfg.is_file():
                shutil.copy2(cfg, tmp / "CsHash.runtimeconfig.json")
            else:
                major = _semver(ver)[0]
                (tmp / "CsHash.runtimeconfig.json").write_text(
                    '{"runtimeOptions": {"tfm": "net%d.0", "framework": '
                    '{"name": "Microsoft.NETCore.App", "version": "%d.0.0"}, '
                    '"rollForward": "LatestMinor"}}\n' % (major, major)
                )
            try:
                os.replace(tmp, out_dir)
            except OSError:
                if not (out_dir / "CsHash.dll").is_file():
                    raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _sdk_dir(self, dotnet: str, root: Path, ver: str) -> Path:
        proc = self._list(dotnet, root, "--list-sdks")
        for line in proc.stdout.splitlines():
            m = _SDK_LINE.match(line.strip())
            if m and m.group(1) == ver:
                return Path(m.group(2)) / ver
        raise HashloomError("bad_toolchain", f"SDK {ver} not found in 'dotnet --list-sdks'")

    def _framework_dir(self, dotnet: str, root: Path, ver: str) -> Path:
        """The newest shared framework of the SDK's own major — the SDK bundle
        always carries its matching runtime, so this exists and its assembly
        versions agree with the SDK's Roslyn."""
        major = _semver(ver)[0]
        proc = self._list(dotnet, root, "--list-runtimes")
        best: tuple[tuple[int, ...], Path] | None = None
        for line in proc.stdout.splitlines():
            m = _RUNTIME_LINE.match(line.strip())
            if m and _semver(m.group(1))[0] == major:
                cand = (_semver(m.group(1)), Path(m.group(2)) / m.group(1))
                if best is None or cand[0] > best[0]:
                    best = cand
        if best is None:
            raise HashloomError(
                "bad_toolchain", f"no Microsoft.NETCore.App {major}.x runtime next to SDK {ver}"
            )
        return best[1]

    def _list(self, dotnet: str, root: Path, flag: str) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [dotnet, flag],
                cwd=root, env=_env(), capture_output=True, text=True, check=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            raise HashloomError("bad_toolchain", f"'{dotnet} {flag}' failed")

    # -- hashing (via the CsHash helper) --------------------------------------

    def impl_hash(self, root: Path, impl: str, contract: str | None = None) -> str:
        path_str, _, qual = impl.partition("::")
        return self._hash_def(root, path_str, qual, contract=contract)

    def _hash_def(self, root: Path, path_str: str, qual: str, contract: str | None = None) -> str:
        dotnet, helper = self._helper(root)
        proc = subprocess.run(
            [dotnet, str(helper), str(root / path_str), qual],
            env=_env(), capture_output=True, text=True, timeout=120,
        )
        kind, _, rest = proc.stdout.strip().partition(" ")
        if kind == "hash":
            return rest
        if kind == "not_found":
            raise HashloomError("impl_not_found", rest, contract=contract)
        if kind == "syntax":
            raise HashloomError("impl_syntax_error", rest, contract=contract)
        # the helper itself could not run (framework mismatch, helper error, ...)
        raise HashloomError(
            "tests_failed_to_run",
            tokens.truncate("cs ast helper failed: " + _oneline(proc.stderr or proc.stdout), 60),
        )

    def test_source_hash(self, root: Path, node_ids: list[str]) -> str:
        parts = []
        for nid in sorted(node_ids):
            path_str, _, test = nid.partition("::")
            h = None
            if path_str and test:
                # a C# test node id names a method (dotted for nested classes);
                # its top-level class is the file's stem
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

    # -- running tests (dotnet test over the root project/solution) -----------

    def run_tests(
        self, root: Path, node_ids: list[str], toolchain: str, timeout: int | float
    ) -> tuple[bool, str]:
        if not self._has_project(root):
            raise HashloomError(
                "bad_toolchain",
                "no .sln or .csproj at the project root — C# tests run via dotnet test",
            )
        cmd = [toolchain, "test", "--nologo", "--filter", self._filter(node_ids)]
        try:
            proc = subprocess.run(
                cmd, cwd=root, env=_env(), capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            raise HashloomError(
                "tests_failed_to_run", f"dotnet test timed out after {timeout:g}s"
            )
        return self._parse_test(proc)

    def _has_project(self, root: Path) -> bool:
        return any(
            next(root.glob(pat), None) is not None for pat in ("*.sln", "*.slnx", "*.csproj")
        )

    def _filter(self, node_ids: list[str]) -> str:
        # VSTest filter grammar, shared by xUnit/NUnit/MSTest: contains-match on
        # FullyQualifiedName absorbs the namespace, `+` is the nested-class
        # spelling in runtime names
        clauses = []
        for nid in sorted(node_ids):
            path_str, _, test = nid.partition("::")
            nested, _, method = test.rpartition(".")
            cls = Path(path_str).stem
            if nested:
                cls += "+" + nested.replace(".", "+")
            clauses.append(f"FullyQualifiedName~{cls}.{method}")
        return "|".join(clauses)

    def _parse_test(self, proc: subprocess.CompletedProcess) -> tuple[bool, str]:
        if proc.returncode == 0:
            return (True, "")
        lines = (proc.stdout + "\n" + proc.stderr).splitlines()
        for i, line in enumerate(lines):
            m = _FAIL_LINE.match(line)
            if not m:
                continue
            # the console logger prints `Error Message:` then the message lines
            detail = "failed"
            for j, nxt in enumerate(lines[i + 1: i + 6]):
                if nxt.strip() == "Error Message:":
                    detail = next(
                        (l.strip() for l in lines[i + 1 + j + 1: i + 1 + j + 4] if l.strip()),
                        "failed",
                    )
                    break
            return (False, tokens.truncate(f"{m.group(1)}: {_oneline(detail)}", SUMMARY_MAX_TOKENS))
        # non-zero exit with no failed-test line: the build or runner could not
        # run (compile error, restore failure, no matching tests, ...)
        first_error = next(
            (l.strip() for l in lines if " error " in l or l.strip().startswith("error ")),
            _oneline(proc.stderr or proc.stdout),
        )
        raise HashloomError(
            "tests_failed_to_run",
            tokens.truncate("dotnet test could not run: " + _oneline(first_error), 60),
        )
