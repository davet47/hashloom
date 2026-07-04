"""`heddle verify` from the command line: same cached verification as the MCP
tool, with a process exit code so it gates CI / pre-commit."""

from __future__ import annotations

import json

import pytest

from heddle import __version__
from heddle.cli import main


def test_version_flag_prints_version_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:  # argparse's version action exits
        main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_verify_cli_passes_with_zero_exit(project, monkeypatch, capsys):
    root, _ = project
    monkeypatch.chdir(root)
    rc = main(["verify", "total", "report"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert {r["status"] for r in out["results"]} <= {"pass", "cached-pass"}


def test_verify_cli_fails_with_nonzero_exit(project, monkeypatch, capsys):
    root, _ = project
    calc = root / "src" / "calc.py"
    calc.write_text(calc.read_text().replace("if i.ok", "if True"))
    monkeypatch.chdir(root)
    rc = main(["verify", "total"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["results"][0]["status"] == "fail"


def test_verify_cli_radius_gates_the_blast_radius(project, monkeypatch, capsys):
    root, _ = project
    monkeypatch.chdir(root)
    # Item is spec-only, so --radius gates its dependents (total, report)
    rc = main(["verify", "--radius", "Item"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True
    assert {r["name"] for r in out["results"]} == {"total", "report"}
    calc = root / "src" / "calc.py"
    calc.write_text(calc.read_text().replace("if i.ok", "if True"))
    rc = main(["verify", "--radius", "Item"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["ok"] is False


def test_verify_cli_unknown_contract_errors_nonzero(project, monkeypatch, capsys):
    root, _ = project
    monkeypatch.chdir(root)
    rc = main(["verify", "nope"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["results"][0]["status"] == "error"
    assert out["results"][0]["error"]["code"] == "unknown_contract"


def test_verify_cli_outside_project_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # no .heddle/ anywhere above
    rc = main(["verify", "total"])
    err = json.loads(capsys.readouterr().err)
    assert rc == 1
    assert err["error"]["code"] == "no_project"
