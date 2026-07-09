"""--no-pycache-trust: clear the project's __pycache__ before a verify run so a
stale .pyc (same size, same mtime-second as the source) can't be loaded.
Virtualenvs and the store are never touched. — ISSUES: stale bytecode."""

from __future__ import annotations

import json

import pytest

from hashloom import api
from hashloom.config import config_path, resolve_pycache_trust
from hashloom.errors import HashloomError
from hashloom.verify import clear_pycache


def _write_config(root, obj) -> None:
    (root / ".hashloom").mkdir(parents=True, exist_ok=True)
    config_path(root).write_text(json.dumps(obj), encoding="utf-8")


# -- config resolution ------------------------------------------------------


def test_pycache_trust_defaults_true(tmp_path):
    assert resolve_pycache_trust(tmp_path) is True


def test_pycache_trust_from_config(tmp_path):
    _write_config(tmp_path, {"pycache_trust": False})
    assert resolve_pycache_trust(tmp_path) is False


def test_pycache_trust_override_beats_config(tmp_path):
    _write_config(tmp_path, {"pycache_trust": True})
    assert resolve_pycache_trust(tmp_path, override=False) is False


def test_bad_pycache_trust_raises_bad_config(tmp_path):
    _write_config(tmp_path, {"pycache_trust": "yes"})
    with pytest.raises(HashloomError) as e:
        resolve_pycache_trust(tmp_path)
    assert e.value.code == "bad_config"


# -- clearing ---------------------------------------------------------------


def test_clear_pycache_removes_project_skips_venv_and_store(tmp_path):
    (tmp_path / "src" / "__pycache__").mkdir(parents=True)
    (tmp_path / "src" / "__pycache__" / "m.pyc").write_bytes(b"x")
    (tmp_path / ".venv" / "lib" / "__pycache__").mkdir(parents=True)  # must survive
    (tmp_path / ".hashloom" / "__pycache__").mkdir(parents=True)  # must survive
    removed = clear_pycache(tmp_path)
    assert removed == 1
    assert not (tmp_path / "src" / "__pycache__").exists()
    assert (tmp_path / ".venv" / "lib" / "__pycache__").exists()
    assert (tmp_path / ".hashloom" / "__pycache__").exists()


def test_clear_pycache_detaches_symlinked_cache_without_touching_target(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    (target / "precious.pyc").write_bytes(b"keep")
    (tmp_path / "pkg").mkdir()
    link = tmp_path / "pkg" / "__pycache__"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not support symlinks")
    removed = clear_pycache(tmp_path)
    assert removed == 1
    assert not link.is_symlink()  # the link is detached
    assert (target / "precious.pyc").exists()  # its target is left untouched


# -- threaded through verify ------------------------------------------------


def test_verify_no_trust_clears_before_running(project):
    root, store = project
    stale = root / "src" / "__pycache__"
    stale.mkdir(parents=True, exist_ok=True)
    (stale / "stale.pyc").write_bytes(b"junk")
    out = api.verify(root, store, ["total"], pycache_trust=False)
    assert out["results"][0]["status"] == "pass"
    assert not stale.exists()  # cleared before the pytest run


def test_verify_trust_leaves_pycache(project):
    root, store = project
    keep = root / "src" / "__pycache__"
    keep.mkdir(parents=True, exist_ok=True)
    (keep / "keep.pyc").write_bytes(b"junk")
    api.verify(root, store, ["total"], pycache_trust=True)
    assert keep.exists()  # default trust must not nuke bytecode
