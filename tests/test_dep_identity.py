"""The dependency set in the toolchain identity: a committed lockfile/manifest
adds a ` deps <file>=<digest12>` suffix, so a green from a different declared
dependency set is never trusted — while a project with no dependency source
keeps the version-only identity byte-identically (absence never busts keys)."""

from __future__ import annotations

import re

from hashloom import api
from hashloom.indexer import index
from hashloom.langs import adapter_for
from hashloom.langs.deps import dep_suffix
from hashloom.project import db_path
from hashloom.store import SqliteStore
from hashloom.verify import verification_key

from .test_toolchain_key import _project

_SUFFIX = re.compile(r"^ deps [\w.\-]+=[0-9a-f]{12}$")


# -- dep_suffix unit ----------------------------------------------------------


def test_empty_root_has_no_suffix(tmp_path):
    assert dep_suffix(tmp_path, ("uv.lock", "requirements.txt")) == ""


def test_suffix_format(tmp_path):
    (tmp_path / "uv.lock").write_text("version = 1\n")
    s = dep_suffix(tmp_path, ("uv.lock",))
    assert _SUFFIX.match(s)
    assert s.startswith(" deps uv.lock=")


def test_candidate_precedence_and_switch(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.32.0\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    assert "uv.lock=" in dep_suffix(tmp_path, ("uv.lock", "requirements.txt"))
    (tmp_path / "uv.lock").unlink()
    assert "requirements.txt=" in dep_suffix(tmp_path, ("uv.lock", "requirements.txt"))


def test_content_sensitivity(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text("a==1\n")
    first = dep_suffix(tmp_path, ("uv.lock",))
    lock.write_text("a==2\n")
    assert dep_suffix(tmp_path, ("uv.lock",)) != first
    lock.write_text("a==1\n")  # byte-identical rewrite -> same digest
    assert dep_suffix(tmp_path, ("uv.lock",)) == first


def test_crlf_and_lf_content_share_a_digest(tmp_path):
    # the cross-OS pin: git autocrlf must never fork the cache per platform
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    (a / "uv.lock").write_bytes(b"alpha==1\nbeta==2\n")
    (b / "uv.lock").write_bytes(b"alpha==1\r\nbeta==2\r\n")
    assert dep_suffix(a, ("uv.lock",)) == dep_suffix(b, ("uv.lock",))


def test_directory_candidate_is_skipped_without_raising(tmp_path):
    (tmp_path / "uv.lock").mkdir()  # a directory, not a lockfile
    (tmp_path / "requirements.txt").write_text("x==1\n")
    assert "requirements.txt=" in dep_suffix(tmp_path, ("uv.lock", "requirements.txt"))


def test_empty_file_digests_distinct_from_absent(tmp_path):
    (tmp_path / "uv.lock").write_bytes(b"")
    s = dep_suffix(tmp_path, ("uv.lock",))
    assert _SUFFIX.match(s)  # an empty lockfile is a (strange) dependency source


# -- the Python adapter -------------------------------------------------------


def test_bare_root_identity_is_byte_identical_to_version_only(tmp_path):
    # THE zero-cold-start pin: dep-free projects keep every key
    ident = adapter_for("x.py::total").toolchain_identity(tmp_path)
    assert re.fullmatch(r"python \S+", ident)


def test_python_identity_gains_dep_suffix(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.32.0\n")
    ident = adapter_for("x.py::total").toolchain_identity(tmp_path)
    parts = ident.split(" ")
    assert len(parts) == 4
    assert parts[0] == "python" and parts[2] == "deps"
    assert re.fullmatch(r"requirements\.txt=[0-9a-f]{12}", parts[3])


def test_long_lived_adapter_sees_lockfile_edits(tmp_path):
    adapter = adapter_for("x.py::total")
    (tmp_path / "uv.lock").write_text("a==1\n")
    before = adapter.toolchain_identity(tmp_path)
    # different-LENGTH rewrite sidesteps mtime-granularity flake
    (tmp_path / "uv.lock").write_text("a==1\nb==2\n")
    after = adapter.toolchain_identity(tmp_path)
    assert before != after
    assert before.split(" deps ")[0] == after.split(" deps ")[0]  # same core


def test_version_subprocess_stays_amortized(tmp_path, monkeypatch):
    import subprocess as sp

    calls = []
    real_run = sp.run
    monkeypatch.setattr(sp, "run", lambda *a, **k: calls.append(a) or real_run(*a, **k))
    adapter = adapter_for("x.py::total")
    adapter._id_cache.clear()
    (tmp_path / "uv.lock").write_text("a==1\n")
    adapter.toolchain_identity(tmp_path)
    adapter.toolchain_identity(tmp_path)
    assert len(calls) == 1  # one version spawn across two identity calls


# -- the key and the end-to-end bust ------------------------------------------


def test_different_dep_suffixes_produce_different_keys(tmp_path):
    _project(tmp_path)
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        k_a = verification_key(store, "total", "ih", "th", "python 3.13.5")
        k_b = verification_key(store, "total", "ih", "th", "python 3.13.5 deps uv.lock=a1b2c3d4e5f6")
        k_c = verification_key(store, "total", "ih", "th", "python 3.13.5 deps uv.lock=ffffffffffff")
        assert len({k_a, k_b, k_c}) == 3
    finally:
        store.close()


def test_dep_set_change_busts_cache_and_status_agrees(tmp_path):
    _project(tmp_path)
    store = SqliteStore(db_path(tmp_path))
    try:
        index(tmp_path, store)
        assert api.verify(tmp_path, store, ["total"])["results"][0]["status"] == "pass"
        assert api.verify(tmp_path, store, ["total"])["results"][0]["status"] == "cached-pass"

        # creating a lockfile IS a dep-set change: status flips dirty, verify re-runs
        (tmp_path / "uv.lock").write_text("requests==2.32.0\n")
        assert "total" in api.status(tmp_path, store)["dirty"]
        assert api.verify(tmp_path, store, ["total"])["results"][0]["status"] == "pass"

        # editing it busts again; reverting the bytes revives the cached green
        (tmp_path / "uv.lock").write_text("requests==2.99.0\n")
        assert api.verify(tmp_path, store, ["total"])["results"][0]["status"] == "pass"
        (tmp_path / "uv.lock").write_text("requests==2.32.0\n")
        assert api.verify(tmp_path, store, ["total"])["results"][0]["status"] == "cached-pass"
    finally:
        store.close()
