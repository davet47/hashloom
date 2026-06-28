"""Contract parsing, validation, and canonical hashing.

The contract hash is sha256 over a canonical form: keys sorted, whitespace
normalised, comments stripped (free with YAML parsing), list order preserved
for invariants/examples (order is meaning), deps sorted (order is not),
`impl` and `tests` excluded so relocating files never invalidates.
"""

from __future__ import annotations

import hashlib
import json
import re

import yaml

from .errors import HeddleError

REQUIRED_KEYS = ("name", "signature")
OPTIONAL_KEYS = ("deps", "invariants", "examples", "tests", "impl")
ALLOWED_KEYS = set(REQUIRED_KEYS) | set(OPTIONAL_KEYS)
# Keys excluded from the hash: relocating impl/test files must not invalidate.
HASH_EXCLUDED = {"impl", "tests"}

_WS = re.compile(r"\s+")


def _norm(value: object) -> str:
    """Normalise a scalar to a whitespace-collapsed string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return _WS.sub(" ", str(value).strip())


def validate_name(name: str) -> None:
    """A contract name maps to `contracts/<name>.yaml`, with `/` marking namespace
    subdirectories (`billing/invoice`). Keep it a safe relative path so a name can
    never escape `contracts/`: no absolute paths, no `..`, no backslashes."""
    if "\\" in name:
        raise HeddleError("invalid_name", f"contract name '{name}' must use '/' for namespaces, not backslash", contract=name)
    if name.startswith("/"):
        raise HeddleError("invalid_name", f"contract name '{name}' must be relative, not absolute", contract=name)
    if any(part in ("", ".", "..") for part in name.split("/")):
        raise HeddleError("invalid_name", f"contract name '{name}' has an empty or '.'/'..' path segment", contract=name)


def parse_contract(text: str, expect_name: str | None = None) -> dict:
    """Parse and validate one contract YAML document. Returns the raw dict."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise HeddleError("invalid_yaml", f"contract is not valid YAML: {e}", contract=expect_name)

    if not isinstance(data, dict):
        raise HeddleError("invalid_shape", "contract must be a YAML mapping", contract=expect_name)

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HeddleError("invalid_shape", "contract must have a non-empty string 'name'", contract=expect_name)
    name = name.strip()
    validate_name(name)
    if expect_name is not None and name != expect_name:
        raise HeddleError(
            "name_mismatch",
            f"contract 'name: {name}' does not match expected '{expect_name}'",
            contract=expect_name,
        )

    unknown = set(data) - ALLOWED_KEYS
    if unknown:
        raise HeddleError(
            "invalid_shape",
            f"unknown keys: {sorted(unknown)} — allowed: {sorted(ALLOWED_KEYS)}",
            contract=name,
        )
    for key in REQUIRED_KEYS:
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise HeddleError("invalid_shape", f"'{key}' is required and must be a non-empty string", contract=name)

    for key in ("deps", "invariants", "tests"):
        if key in data:
            if not isinstance(data[key], list) or not all(isinstance(x, str) and x.strip() for x in data[key]):
                raise HeddleError("invalid_shape", f"'{key}' must be a list of non-empty strings", contract=name)

    if "examples" in data:
        if not isinstance(data["examples"], list):
            raise HeddleError("invalid_shape", "'examples' must be a list of {in, out} mappings", contract=name)
        for ex in data["examples"]:
            if not isinstance(ex, dict) or set(ex) != {"in", "out"}:
                raise HeddleError("invalid_shape", "each example must be a mapping with exactly 'in' and 'out'", contract=name)

    if "impl" in data:
        impl = data["impl"]
        if not isinstance(impl, str) or "::" not in impl:
            raise HeddleError("invalid_shape", "'impl' must be 'path/to/file.py::function_name'", contract=name)

    return data


def canonical_form(data: dict) -> str:
    """Deterministic JSON rendering of the hash-relevant contract content."""
    canon: dict = {
        "name": _norm(data["name"]),
        "signature": _norm(data["signature"]),
        # deps order carries no meaning — sorted so reordering never invalidates
        "deps": sorted(_norm(d) for d in data.get("deps", [])),
        # invariant/example order is meaning — preserved
        "invariants": [_norm(i) for i in data.get("invariants", [])],
        "examples": [{"in": _norm(ex["in"]), "out": _norm(ex["out"])} for ex in data.get("examples", [])],
    }
    return json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def contract_hash(data: dict) -> str:
    return hashlib.sha256(canonical_form(data).encode("utf-8")).hexdigest()


def _list_diff(old: list[str], new: list[str]) -> dict:
    """added / removed / reordered for an order-significant list of strings.

    Membership is by value; `reordered` is reported only when the two lists hold
    the same values in a different order, so a pure reorder (which the hash does
    treat as meaning) is distinguishable from add/remove churn.
    """
    olds, news = set(old), set(new)
    out: dict = {}
    added = [x for x in new if x not in olds]
    removed = [x for x in old if x not in news]
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    if not added and not removed and old != new:
        out["reordered"] = True
    return out


def _example_diff(old_ex: list[dict], new_ex: list[dict]) -> dict:
    """Order-significant diff over examples, comparing normalised (in, out) pairs."""
    def keys(exs: list[dict]) -> list[tuple[str, str]]:
        return [(_norm(e["in"]), _norm(e["out"])) for e in exs]

    o_keys, n_keys = keys(old_ex), keys(new_ex)
    o_set, n_set = set(o_keys), set(n_keys)
    out: dict = {}
    added = [{"in": i, "out": o} for (i, o) in n_keys if (i, o) not in o_set]
    removed = [{"in": i, "out": o} for (i, o) in o_keys if (i, o) not in n_set]
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    if not added and not removed and o_keys != n_keys:
        out["reordered"] = True
    return out


def diff_contracts(old: dict, new: dict) -> dict:
    """Field-level semantic diff between two parsed contracts.

    Normalises every field with `_norm`, exactly as the hash does, so a
    cosmetic-only edit (whitespace, comments, key/dep order) yields an empty
    diff: the same edits the contract hash ignores. Only changed fields appear.
    `impl` and `tests` are excluded from the hash, but a change to them is still
    reported here, since it is real and worth surfacing to an agent.
    """
    diff: dict = {}

    o_sig, n_sig = _norm(old["signature"]), _norm(new["signature"])
    if o_sig != n_sig:
        diff["signature"] = {"old": o_sig, "new": n_sig}

    # deps carry no order meaning, so compare as sets and never report a reorder
    o_deps = {_norm(d) for d in old.get("deps", [])}
    n_deps = {_norm(d) for d in new.get("deps", [])}
    dep: dict = {}
    if n_deps - o_deps:
        dep["added"] = sorted(n_deps - o_deps)
    if o_deps - n_deps:
        dep["removed"] = sorted(o_deps - n_deps)
    if dep:
        diff["deps"] = dep

    inv = _list_diff([_norm(i) for i in old.get("invariants", [])], [_norm(i) for i in new.get("invariants", [])])
    if inv:
        diff["invariants"] = inv

    ex = _example_diff(old.get("examples", []), new.get("examples", []))
    if ex:
        diff["examples"] = ex

    if _norm(old.get("impl", "")) != _norm(new.get("impl", "")):
        diff["impl"] = {"old": old.get("impl"), "new": new.get("impl")}
    o_tests = [_norm(t) for t in old.get("tests", [])]
    n_tests = [_norm(t) for t in new.get("tests", [])]
    if o_tests != n_tests:
        diff["tests"] = {"old": old.get("tests", []), "new": new.get("tests", [])}

    return diff
