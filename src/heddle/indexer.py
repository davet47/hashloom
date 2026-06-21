"""Rebuild the store from the contracts/ folder. The store is always derived."""

from __future__ import annotations

from pathlib import Path

import yaml

from .contract import contract_hash, parse_contract
from .errors import HeddleError, unknown_name
from .implhash import impl_hash
from .project import contracts_dir
from .store import Store


def index(root: Path, store: Store) -> dict:
    """Parse every contract, validate cross-references, rebuild contracts/edges/impls.

    Verification rows are keyed by content hashes, so they survive reindexing;
    contracts whose hash changed get their dependents' verifications marked stale.
    """
    cdir = contracts_dir(root)
    if not cdir.is_dir():
        raise HeddleError("no_contracts", f"'{cdir}' does not exist")

    # recurse: a subdirectory is a namespace, so contracts/billing/invoice.yaml
    # is the contract `billing/invoice` (its name must match its path under cdir)
    files = sorted(cdir.rglob("*.yaml")) + sorted(cdir.rglob("*.yml"))
    parsed: dict[str, tuple[dict, str]] = {}
    for f in files:
        rel = f.relative_to(cdir)
        if any(part.startswith(".") for part in rel.parts):
            continue  # hidden / vendored files and dirs are not contracts
        text = f.read_text(encoding="utf-8")
        try:
            probe = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise HeddleError("invalid_yaml", f"'{rel.as_posix()}' is not valid YAML: {e}")
        if not (isinstance(probe, dict) and "name" in probe and "signature" in probe):
            # a contract self-identifies by its two required keys; other YAML under
            # contracts/ (mkdocs, CI, compose, data fixtures) is skipped, not fatal.
            # A doc with both keys but a wrong name still trips name_mismatch below.
            continue
        expect = rel.with_suffix("").as_posix()
        data = parse_contract(text, expect_name=expect)
        if data["name"] in parsed:
            raise HeddleError(
                "duplicate_contract",
                f"contract '{data['name']}' is defined by more than one file",
                contract=data["name"],
            )
        parsed[data["name"]] = (data, text)

    # two-pass: all names known before deps are validated
    for name, (data, _) in parsed.items():
        for dep in data.get("deps", []):
            if dep not in parsed:
                raise unknown_name("unknown_dep", dep, list(parsed), contract=name)

    old_hashes = store.contract_hashes()
    changed: list[str] = []
    for name, (data, yaml_text) in parsed.items():
        chash = contract_hash(data)
        if old_hashes.get(name) != chash:
            changed.append(name)
        store.upsert_contract(name, chash, yaml_text)
        store.set_deps(name, data.get("deps", []))
        if "impl" in data:
            path_str = data["impl"].partition("::")[0]
            try:
                ihash = impl_hash(root, data["impl"], contract=name)
            except HeddleError:
                ihash = None  # missing impl shows up as dirty in status, not an index failure
            store.upsert_impl(name, ihash, path_str)

    removed = [n for n in old_hashes if n not in parsed]
    for name in removed:
        store.delete_contract(name)

    invalidated: set[str] = set()
    for name in changed + removed:
        invalidated.update(store.dependents_of(name, transitive=True))
        invalidated.add(name)
    store.mark_stale(sorted(invalidated & set(parsed)))

    return {
        "indexed": len(parsed),
        "changed": sorted(changed),
        "removed": sorted(removed),
        "invalidated": sorted(invalidated & set(parsed)),
    }
