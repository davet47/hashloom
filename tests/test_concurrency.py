"""put_contract under concurrent writers: atomic file writes (no torn contract)
and a per-name lock (no file/store divergence) — ISSUES: concurrent writers.

Each thread opens its own Store — sqlite connections are single-thread, and it
mirrors the real case of independent agents/processes weaving in parallel.
"""

from __future__ import annotations

import concurrent.futures

import yaml

from heddle import api
from heddle.contract import contract_hash, parse_contract
from heddle.project import db_path
from heddle.store import Store


def _contract(name: str, sig: str = "() -> None") -> str:
    return f'name: {name}\nsignature: "{sig}"\n'


def _put(root, name: str, text: str) -> None:
    store = Store(db_path(root))
    try:
        api.put_contract(root, store, name, text)
    finally:
        store.close()


def test_concurrent_distinct_names_all_land(project):
    root, _ = project
    names = [f"unit{i}" for i in range(16)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda n: _put(root, n, _contract(n)), names))

    check = Store(db_path(root))
    try:
        for n in names:
            text = (root / "contracts" / f"{n}.yaml").read_text()
            assert yaml.safe_load(text)["name"] == n  # whole file, not half-written
            assert check.get_contract(n) is not None  # and recorded in the store
    finally:
        check.close()


def test_concurrent_same_name_never_torn_or_divergent(project):
    root, _ = project
    name = "racy"
    variants = [_contract(name, f"(x: int) -> r{i}") for i in range(24)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda t: _put(root, name, t), variants))

    text = (root / "contracts" / f"{name}.yaml").read_text()
    assert yaml.safe_load(text)["name"] == name  # valid YAML, not a torn write
    assert text in variants  # exactly one writer's content, never a blend
    # the file and the store agree: recorded hash matches what is on disk
    check = Store(db_path(root))
    try:
        assert check.get_contract(name)["hash"] == contract_hash(parse_contract(text, expect_name=name))
    finally:
        check.close()
