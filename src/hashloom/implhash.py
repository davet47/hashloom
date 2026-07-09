"""Normalised-AST hashing of implementations and tests.

sha256 of `ast.dump` for the named function/class, so formatting and comment
changes never bust the verification cache. Docstrings are stripped before
dumping; they are documentation, not behaviour. The same machinery hashes test
source for the verification key (see `test_source_hash`).
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from .errors import HashloomError

_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _strip_docstrings(node: ast.AST) -> ast.AST:
    for child in ast.walk(node):
        if isinstance(child, (*_DEF_NODES, ast.Module)) and child.body:
            first = child.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                child.body = child.body[1:] or [ast.Pass()]
    return node


def _find_def(tree: ast.Module, qualname: str) -> ast.AST | None:
    """Resolve a possibly-dotted name (e.g. 'Class.method') to its def node."""
    scope: list[ast.AST] = list(tree.body)
    node: ast.AST | None = None
    for part in qualname.split("."):
        node = next(
            (n for n in scope if isinstance(n, _DEF_NODES) and n.name == part),
            None,
        )
        if node is None:
            return None
        scope = list(getattr(node, "body", []))
    return node


def _hash_def(root: Path, path_str: str, qualname: str, contract: str | None = None) -> str:
    """sha256 of the normalised, docstring-stripped AST of `path_str::qualname`."""
    path = root / path_str
    if not path.is_file():
        raise HashloomError("impl_not_found", f"file '{path_str}' does not exist", contract=contract)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        raise HashloomError("impl_syntax_error", f"'{path_str}' line {e.lineno}: {e.msg}", contract=contract)

    node = _find_def(tree, qualname)
    if node is None:
        raise HashloomError("impl_not_found", f"no function or class '{qualname}' in '{path_str}'", contract=contract)

    dumped = ast.dump(_strip_docstrings(node), annotate_fields=True, include_attributes=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def impl_hash(root: Path, impl: str, contract: str | None = None) -> str:
    """Hash the implementation referenced by 'path/to/file.py::qualname'."""
    path_str, _, qualname = impl.partition("::")
    return _hash_def(root, path_str, qualname, contract=contract)


def test_source_hash(root: Path, node_ids: list[str]) -> str:
    """Combined hash of the source of each pytest test, for the verification key.

    Each node id `path::Class::func[param]` is resolved to its function or class
    definition and hashed with the same normalised-AST method as `impl_hash`, so
    reformatting, comments, and docstrings in a test never bust the cache but a
    real change to its body does. A node id whose source can't be resolved
    (missing file, parametrise-only id, unusual shape) falls back to the id
    string, so the key still tracks the test set and a verify never fails just
    because a test couldn't be parsed. Ids are sorted, so their order in the
    contract's `tests` field carries no meaning.

    Limitation: this hashes each test's own definition, not conftest fixtures or
    helper functions it calls; changing only those will not force a re-run yet.
    """
    parts = []
    for nid in sorted(node_ids):
        path_str, _, rest = nid.partition("::")
        qualname = ".".join(seg.split("[", 1)[0] for seg in rest.split("::")) if rest else ""
        h = None
        if qualname:
            try:
                h = _hash_def(root, path_str, qualname)
            # OSError/ValueError cover unreadable and non-UTF-8 files — the
            # degrade-to-id promise holds even for sources we cannot decode
            except (HashloomError, OSError, ValueError):
                h = None
        parts.append(f"{nid}={h or 'id'}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
