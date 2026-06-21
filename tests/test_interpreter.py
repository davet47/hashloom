"""Interpreter resolution for the verify runner: precedence (override > config >
auto-detected .venv > sys.executable), clean errors on bad config / bad python,
and the resolved interpreter threading end-to-end through verify."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from heddle import api
from heddle.config import DEFAULT_TIMEOUT, config_path, load_config, resolve_python, resolve_timeout
from heddle.errors import HeddleError


def write_config(root: Path, obj) -> None:
    cfg = root / ".heddle"
    cfg.mkdir(parents=True, exist_ok=True)
    config_path(root).write_text(json.dumps(obj), encoding="utf-8")


def fake_python(root: Path, rel: str = ".venv/bin/python") -> Path:
    """A real, executable interpreter at <root>/<rel> (symlink to this python)."""
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(sys.executable)
    return target


# -- precedence -------------------------------------------------------------


def test_default_falls_back_to_sys_executable(tmp_path):
    assert resolve_python(tmp_path) == sys.executable


def test_autodetects_project_venv(tmp_path):
    venv = fake_python(tmp_path)
    assert resolve_python(tmp_path) == str(venv)


def test_config_python_beats_autodetect(tmp_path):
    fake_python(tmp_path)  # auto-detectable .venv
    other = fake_python(tmp_path, "tools/py")
    write_config(tmp_path, {"python": str(other)})
    assert resolve_python(tmp_path) == str(other)


def test_relative_config_python_resolves_against_root(tmp_path):
    fake_python(tmp_path, "tools/py")
    write_config(tmp_path, {"python": "tools/py"})
    assert resolve_python(tmp_path) == str(tmp_path / "tools" / "py")


def test_override_beats_config(tmp_path):
    write_config(tmp_path, {"python": str(fake_python(tmp_path))})
    assert resolve_python(tmp_path, override=sys.executable) == sys.executable


# -- clean failures ---------------------------------------------------------


def test_malformed_config_raises_bad_config(tmp_path):
    (tmp_path / ".heddle").mkdir()
    config_path(tmp_path).write_text("{not json", encoding="utf-8")
    with pytest.raises(HeddleError) as e:
        resolve_python(tmp_path)
    assert e.value.code == "bad_config"


def test_non_object_config_raises_bad_config(tmp_path):
    write_config(tmp_path, ["not", "an", "object"])
    with pytest.raises(HeddleError) as e:
        load_config(tmp_path)
    assert e.value.code == "bad_config"


def test_explicit_missing_interpreter_raises_bad_python(tmp_path):
    with pytest.raises(HeddleError) as e:
        resolve_python(tmp_path, override="/no/such/python")
    assert e.value.code == "bad_python"


def test_config_missing_interpreter_raises_bad_python(tmp_path):
    write_config(tmp_path, {"python": "/no/such/python"})
    with pytest.raises(HeddleError) as e:
        resolve_python(tmp_path)
    assert e.value.code == "bad_python"


def test_absent_config_is_empty(tmp_path):
    assert load_config(tmp_path) == {}


# -- verify_timeout ---------------------------------------------------------


def test_timeout_defaults(tmp_path):
    assert resolve_timeout(tmp_path) == DEFAULT_TIMEOUT


def test_timeout_from_config(tmp_path):
    write_config(tmp_path, {"verify_timeout": 30})
    assert resolve_timeout(tmp_path) == 30


@pytest.mark.parametrize("bad", [0, -5, "30", True])
def test_bad_timeout_raises_bad_config(tmp_path, bad):
    write_config(tmp_path, {"verify_timeout": bad})
    with pytest.raises(HeddleError) as e:
        resolve_timeout(tmp_path)
    assert e.value.code == "bad_config"


# -- threads end-to-end -----------------------------------------------------


def test_verify_threads_explicit_python(project):
    root, store = project
    out = api.verify(root, store, ["total"], python=sys.executable)
    assert out["results"][0]["status"] == "pass"


def test_status_reports_resolved_python(project):
    root, store = project  # no .venv in the fixture project
    assert api.status(root, store)["python"] == sys.executable
