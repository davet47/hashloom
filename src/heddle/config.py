"""Interpreter resolution for the verify pytest runner.

`verify` shells pytest out to a python interpreter; which one is resolved by
precedence (most explicit first):

  1. an explicit override — the ``heddle serve --python PATH`` flag
  2. ``.heddle/config.json`` -> ``{"python": "..."}``
  3. an auto-detected project venv (``<root>/.venv/bin/python``, ...)
  4. ``sys.executable`` — the interpreter running heddle itself (the v0.1 default)

This lets heddle, even installed globally, run a target project's tests against
that project's own venv — without being installed into it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .errors import HeddleError
from .project import HEDDLE_DIR

CONFIG_NAME = "config.json"
DEFAULT_TIMEOUT = 300  # seconds for a single pytest run; override via verify_timeout

# checked in order; first one that exists wins. The .heddle/config.json file is
# the future home for other project settings too (e.g. the verify timeout).
_VENV_CANDIDATES = (
    ".venv/bin/python",
    ".venv/bin/python3",
    "venv/bin/python",
    "venv/bin/python3",
    ".venv/Scripts/python.exe",  # Windows
)


def config_path(root: Path) -> Path:
    return root / HEDDLE_DIR / CONFIG_NAME


def load_config(root: Path) -> dict:
    """Read .heddle/config.json. Returns {} if absent; raises on malformed JSON."""
    path = config_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise HeddleError("bad_config", f"could not read {path.name}: {e}")
    if not isinstance(data, dict):
        raise HeddleError("bad_config", f"{path.name} must be a JSON object")
    return data


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _check(path: Path, source: str, raw: str) -> str:
    """Validate an explicitly-configured interpreter — fail clean if unusable."""
    if not _is_executable(path):
        raise HeddleError("bad_python", f"{source} '{raw}' is not an executable interpreter")
    return str(path)


def resolve_python(root: Path, override: str | None = None) -> str:
    """Resolve the interpreter verify should run pytest with. See module docstring."""
    if override is not None:
        return _check(Path(override).expanduser(), "--python", override)

    configured = load_config(root).get("python")
    if configured:
        p = Path(configured).expanduser()
        if not p.is_absolute():
            p = root / p  # config paths are project-relative
        return _check(p, ".heddle/config.json python", configured)

    for rel in _VENV_CANDIDATES:
        cand = root / rel
        if _is_executable(cand):
            return str(cand)

    return sys.executable


def resolve_timeout(root: Path) -> int | float:
    """Per-run pytest timeout in seconds (.heddle/config.json verify_timeout)."""
    value = load_config(root).get("verify_timeout")
    if value is None:
        return DEFAULT_TIMEOUT
    # bool is an int subclass — reject it explicitly so `true` isn't read as 1
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise HeddleError("bad_config", f"verify_timeout must be a positive number, got {value!r}")
    return value


def resolve_pycache_trust(root: Path, override: bool | None = None) -> bool:
    """Whether verify may trust pre-existing __pycache__ (default True).

    The runner already passes -B / PYTHONDONTWRITEBYTECODE so its own runs never
    write bytecode, but a stale user-written .pyc that happens to share the
    source's size and mtime-second could still be loaded. Set `pycache_trust:
    false` in .heddle/config.json (or pass `--no-pycache-trust`) to clear the
    project's bytecode caches before each verify run instead.
    """
    if override is not None:
        return override
    value = load_config(root).get("pycache_trust")
    if value is None:
        return True
    if not isinstance(value, bool):
        raise HeddleError("bad_config", f"pycache_trust must be true or false, got {value!r}")
    return value
