"""The spec-kit extension: manifest sanity, command prompts, and the gate script
end-to-end against a real hashloom project."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

EXT = Path(__file__).resolve().parent.parent / "integrations" / "speckit-hashloom"
GATE = EXT / "scripts" / "bash" / "hashloom-gate.sh"

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
# the console script lands on PATH via `uv sync`; skip cleanly elsewhere
needs_hashloom = pytest.mark.skipif(
    shutil.which("hashloom") is None, reason="hashloom CLI not on PATH"
)


def manifest():
    return yaml.safe_load((EXT / "extension.yml").read_text())


def frontmatter(md_path):
    text = md_path.read_text()
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n")[1])


def run_gate(root, mode, feature_dir, env=None):
    proc = subprocess.run(
        ["bash", str(GATE), mode, str(feature_dir)],
        cwd=root, capture_output=True, text=True, env=env,
    )
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, out, proc.stderr


@pytest.fixture
def feature(project):
    root, store = project
    store.close()  # the gate's subprocesses open their own connections
    fdir = root / "specs" / "001-calc"
    fdir.mkdir(parents=True)
    (fdir / "seams.txt").write_text(
        "# hashloom seams for 001-calc\nItem\ntotal\nreport\n"
    )
    return root, fdir


# -- manifest and command prompts (hermetic) ----------------------------------


def test_manifest_parses_with_required_keys():
    m = manifest()
    assert m["schema_version"] == "1.0"
    ext = m["extension"]
    for key in ("id", "name", "version", "description", "author", "repository", "license"):
        assert ext[key]
    assert ext["id"] == "hashloom"
    assert m["requires"]["tools"][0]["name"] == "hashloom"
    assert m["requires"]["speckit_version"]


def test_command_names_match_speckit_pattern_and_files_exist():
    for cmd in manifest()["provides"]["commands"]:
        assert re.fullmatch(r"speckit\.hashloom\.[a-z0-9-]+", cmd["name"])
        assert (EXT / cmd["file"]).is_file()
        assert cmd["description"]


def test_hooks_reference_provided_commands_without_conditions():
    m = manifest()
    provided = {c["name"] for c in m["provides"]["commands"]}
    assert set(m["hooks"]) == {"before_implement", "after_implement"}
    for hook in m["hooks"].values():
        assert hook["command"] in provided
        assert hook["optional"] is False
        # spec-kit's implement command skips conditioned hooks outright
        assert "condition" not in hook


def test_command_frontmatter_parses():
    for md in (EXT / "commands").glob("*.md"):
        assert frontmatter(md)["description"]


def test_seams_command_teaches_the_workflow():
    text = (EXT / "commands" / "speckit.hashloom.seams.md").read_text()
    for load_bearing in (
        "status: inferred",
        "hashloom index",
        "hashloom status",
        "seams.txt",
        "Do NOT contract",
        "PROJECT ROOT `contracts/`",
        "unknown keys",
    ):
        assert load_bearing in text


def test_gate_script_referenced_by_command_exists_and_is_executable():
    text = (EXT / "commands" / "speckit.hashloom.gate.md").read_text()
    assert "scripts/bash/hashloom-gate.sh" in text
    assert GATE.is_file()
    assert os.access(GATE, os.X_OK)


# -- the gate script end-to-end -----------------------------------------------


@needs_bash
@needs_hashloom
def test_gate_first_run_passes_then_cached(feature):
    root, fdir = feature
    rc, out, _ = run_gate(root, "gate", fdir)
    assert rc == 0 and out["ok"] is True
    assert set(out["results"]["pass"]) == {"total", "report"}
    assert out["spec_only"] == ["Item"]  # spec-only type: --radius drops it
    rc, out, _ = run_gate(root, "gate", fdir)
    assert rc == 0 and out["ok"] is True
    assert set(out["results"]["cached_pass"]) == {"total", "report"}
    assert out["spec_only"] == ["Item"]


@needs_bash
@needs_hashloom
def test_gate_red_on_failing_impl_exits_1(feature):
    root, fdir = feature
    run_gate(root, "gate", fdir)  # warm the cache
    calc = root / "src" / "calc.py"
    calc.write_text(calc.read_text().replace("if i.ok", "if True"))
    rc, out, _ = run_gate(root, "gate", fdir)
    assert rc == 1 and out["ok"] is False
    fails = {f["name"] for f in out["results"]["fail"]}
    assert "total" in fails
    assert all(f["summary"] for f in out["results"]["fail"])
    # the cache serves report's green across total's red — the loop's point
    assert "report" in out["results"]["cached_pass"]


@needs_bash
@needs_hashloom
def test_precheck_never_blocks_on_red(feature):
    root, fdir = feature
    run_gate(root, "gate", fdir)
    calc = root / "src" / "calc.py"
    calc.write_text(calc.read_text().replace("if i.ok", "if True"))
    rc, out, _ = run_gate(root, "precheck", fdir)
    assert rc == 0  # precheck reports, never blocks
    assert out["ok"] is False
    assert out["mode"] == "precheck"
    assert "total" in {f["name"] for f in out["results"]["fail"]}


@needs_bash
@needs_hashloom
def test_unknown_seam_fails_the_gate(feature):
    root, fdir = feature
    with open(fdir / "seams.txt", "a") as f:
        f.write("ghost\n")
    rc, out, _ = run_gate(root, "gate", fdir)
    assert rc == 1 and out["ok"] is False
    errors = {e["name"]: e for e in out["results"]["error"]}
    assert errors["ghost"]["code"] == "unknown_contract"


@needs_bash
@needs_hashloom
def test_missing_manifest_is_vacuous_ok(feature):
    root, fdir = feature
    (fdir / "seams.txt").unlink()
    rc, out, _ = run_gate(root, "gate", fdir)
    assert rc == 0 and out["ok"] is True
    assert "no seams manifest" in out["note"]
    assert out["seams"] == []


@needs_bash
@needs_hashloom
def test_empty_manifest_is_vacuous_ok(feature):
    root, fdir = feature
    (fdir / "seams.txt").write_text("# only comments\n\n   \n  # and blanks\n")
    rc, out, _ = run_gate(root, "gate", fdir)
    assert rc == 0 and out["ok"] is True
    assert "lists no names" in out["note"]


@needs_bash
@needs_hashloom
def test_missing_feature_dir_and_bad_mode_are_infra_errors(feature):
    root, fdir = feature
    rc, out, _ = run_gate(root, "gate", root / "specs" / "does-not-exist")
    assert rc == 2
    assert out["error"]["code"] == "no_feature_dir"
    rc, out, _ = run_gate(root, "sideways", fdir)
    assert rc == 2
    assert out["error"]["code"] == "usage"


@needs_bash
@needs_hashloom
def test_uninitialized_project_is_infra_error(tmp_path):
    fdir = tmp_path / "specs" / "001-x"
    fdir.mkdir(parents=True)
    (fdir / "seams.txt").write_text("something\n")
    rc, out, _ = run_gate(tmp_path, "gate", fdir)
    assert rc == 2
    assert out["error"]["code"] == "index_failed"


@needs_bash
@needs_hashloom
def test_hashloom_not_on_path_is_infra_error(feature, tmp_path):
    root, fdir = feature
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "bash").symlink_to(shutil.which("bash"))
    (bindir / "python3").symlink_to(sys.executable)
    rc, out, _ = run_gate(root, "gate", fdir, env={"PATH": str(bindir)})
    assert rc == 2
    assert out["error"]["code"] == "hashloom_not_found"


@needs_bash
@needs_hashloom
def test_inferred_contracts_surface_in_output(feature):
    root, fdir = feature
    total = root / "contracts" / "total.yaml"
    total.write_text(total.read_text() + "status: inferred\n")
    rc, out, _ = run_gate(root, "gate", fdir)  # gate re-indexes the edit
    assert rc == 0 and out["ok"] is True
    assert "total" in out["inferred"]


@needs_bash
@needs_hashloom
def test_gate_reindexes_contract_edits(feature):
    root, fdir = feature
    run_gate(root, "gate", fdir)  # warm the cache
    total = root / "contracts" / "total.yaml"
    total.write_text(total.read_text().replace(
        '"(items: list[Item]) -> float"',
        '"(items: list[Item], default: float = 0.0) -> float"',
    ))
    rc, out, _ = run_gate(root, "gate", fdir)
    assert rc == 0
    # the gate's own `hashloom index` picked up the meaning change, so total
    # re-verified instead of serving the stale green
    assert "total" in out["results"]["pass"]
    assert "total" not in out["results"]["cached_pass"]


@needs_bash
@needs_hashloom
def test_namespaced_seam_name_round_trips(feature):
    root, fdir = feature
    ns = root / "contracts" / "calc"
    ns.mkdir()
    (ns / "extra.yaml").write_text('name: calc/extra\nsignature: "type alias: str"\n')
    with open(fdir / "seams.txt", "a") as f:
        f.write("calc/extra   # namespaced, spec-only\n")
    rc, out, _ = run_gate(root, "gate", fdir)
    assert rc == 0 and out["ok"] is True
    assert "calc/extra" in out["seams"]
    assert "calc/extra" in out["spec_only"]
