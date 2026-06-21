"""Project layout: a heddle project is any directory with a .heddle/ marker.

contracts/ holds one YAML file per unit; .heddle/store.db is derived state.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .errors import HeddleError

try:
    import fcntl  # posix advisory file locks
except ImportError:  # pragma: no cover - non-posix
    fcntl = None  # type: ignore[assignment]

HEDDLE_DIR = ".heddle"
CONTRACTS_DIR = "contracts"
DB_NAME = "store.db"
LOCKS_DIR = "locks"


def find_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / HEDDLE_DIR).is_dir():
            return candidate
    raise HeddleError("no_project", f"no {HEDDLE_DIR}/ found in '{cur}' or any parent — run `heddle init` first")


def db_path(root: Path) -> Path:
    return root / HEDDLE_DIR / DB_NAME


def contracts_dir(root: Path) -> Path:
    return root / CONTRACTS_DIR


def contract_path(root: Path, name: str) -> Path:
    return contracts_dir(root) / f"{name}.yaml"


def init_project(root: Path) -> list[str]:
    """Create .heddle/ and contracts/. Returns the paths created."""
    created = []
    for d in (root / HEDDLE_DIR, contracts_dir(root)):
        if not d.exists():
            d.mkdir(parents=True)
            created.append(str(d))
    return created


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write `text` to `path` so a reader never sees a torn file.

    Writes a sibling temp file, fsyncs it, then `os.replace`s it onto the target
    — atomic on a single filesystem, so a concurrent reader (or a crash) sees
    either the old file or the whole new one, never a half-written contract.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _lock_key(name: str) -> str:
    """A filesystem-safe lock filename for a (possibly namespaced) contract name."""
    return name.replace("/", "__").replace("\\", "__")


@contextmanager
def contract_lock(root: Path, name: str):
    """Serialise concurrent writers of the *same* contract name.

    An exclusive posix advisory lock (`flock`) on `.heddle/locks/<name>.lock`, so
    two agents calling `put_contract` on one name don't interleave their
    file-write + store-update and leave the file and store disagreeing. Where
    `fcntl` is unavailable (Windows) this is a no-op and callers fall back to
    `atomic_write_text` alone for torn-file safety.
    """
    if fcntl is None:  # pragma: no cover - non-posix
        yield
        return
    locks_dir = root / HEDDLE_DIR / LOCKS_DIR
    locks_dir.mkdir(parents=True, exist_ok=True)
    with open(locks_dir / f"{_lock_key(name)}.lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
