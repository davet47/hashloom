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
