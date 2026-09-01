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


# -- the fixture closure, for test_source_hash --------------------------------
#
# pytest injects fixtures by name: a test's arguments, usefixtures marks,
# request.getfixturevalue calls, and autouse fixtures in scope, looked up in
# the test's module first and then its conftest.py chain, nearest wins. The
# requested *names* are already inside the test def's own AST hash; what the
# hash was missing is the resolved *defs* — so only fixtures that resolve to a
# project def contribute components, and a test using nothing but builtins
# (tmp_path, monkeypatch, ...) keeps its pre-fixture-coverage hash unchanged.
# Plugin fixtures ride the dependency-set identity instead.

_FIX_SKIP = frozenset({"request", "self", "cls"})  # never project fixtures


def _dec_tail(node: ast.AST) -> str:
    """The final attribute name of a decorator expression ('fixture' for both
    @fixture and @pytest.fixture, called or not); '' when unrecognisable."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


class _ScannedModule:
    """One test module or conftest: fixtures by requestable name, autouse
    names, and a `dynamic` bit for fixture use no static walk can resolve."""

    def __init__(self, tree: ast.Module):
        self.fixtures: dict[str, ast.AST] = {}
        self.autouse: set[str] = set()
        self.mark_names: set[str] = set()  # module-level pytestmark usefixtures
        self.dynamic = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._scan_def(node)
            elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
            ):
                self.mark_names |= _usefixtures_names(node.value, self)

    def _scan_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            if _dec_tail(dec) != "fixture":
                continue
            name = node.name
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    if kw.arg == "name":
                        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            name = kw.value.value
                        else:
                            self.dynamic = True  # an alias we cannot see through
                    elif kw.arg == "autouse":
                        if isinstance(kw.value, ast.Constant):
                            if kw.value.value:
                                self.autouse.add(name)
                        else:
                            self.dynamic = True
            self.fixtures[name] = node
            break


def _usefixtures_names(node: ast.AST, module: _ScannedModule) -> set[str]:
    """Literal names from every usefixtures(...) call under `node`; a
    non-literal argument flips the module's dynamic bit."""
    names: set[str] = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call) and _dec_tail(call) == "usefixtures":
            for arg in call.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names.add(arg.value)
                else:
                    module.dynamic = True
    return names


def _requested_names(node: ast.AST, module: _ScannedModule) -> set[str]:
    """Names a def pulls in: its parameters, usefixtures decorators, and
    literal getfixturevalue calls; non-literal getfixturevalue is dynamic."""
    names: set[str] = set()
    args = getattr(node, "args", None)
    if args is not None:
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            names.add(a.arg)
    for dec in getattr(node, "decorator_list", []):
        names |= _usefixtures_names(dec, module)
    for call in ast.walk(node):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "getfixturevalue"
        ):
            if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                names.add(call.args[0].value)
            else:
                module.dynamic = True
    return names - _FIX_SKIP


def _node_hash(node: ast.AST) -> str:
    return hashlib.sha256(
        ast.dump(_strip_docstrings(node), annotate_fields=True, include_attributes=False).encode("utf-8")
    ).hexdigest()


def _chain_paths(root: Path, path_str: str) -> list[tuple[str, Path]]:
    """(rel, abs) of the test module and its conftest chain up to root,
    nearest first — pytest's lookup order. Empty when the module is missing."""
    path = root / path_str
    if not path.is_file():
        return []
    out = [(path_str, path)]
    d = path.parent
    while True:
        try:
            d.relative_to(root)
        except ValueError:
            break
        conftest = d / "conftest.py"
        if conftest.is_file():
            out.append((conftest.relative_to(root).as_posix(), conftest))
        if d == root:
            break
        d = d.parent
    return out


def _file_hash(path: Path) -> str:
    """Whole-module normalised hash; raw bytes when the file will not parse —
    over-sensitive, never under-sensitive, never raising."""
    try:
        raw = path.read_bytes()
    except OSError:
        return "unreadable"
    try:
        return _node_hash(ast.parse(raw.decode("utf-8")))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return hashlib.sha256(raw).hexdigest()


def _resolve_fixtures(
    chain: list[tuple[str, Path]], qualname: str, cache: dict
) -> tuple[dict[str, str], bool]:
    """({'name@file': def_hash}, dynamic) for one test's fixture closure."""
    modules: list[tuple[str, ast.Module, _ScannedModule]] = []
    for rel, p in chain:
        if rel not in cache:
            tree = ast.parse(p.read_text(encoding="utf-8"))
            cache[rel] = (tree, _ScannedModule(tree))
        modules.append((rel, *cache[rel]))

    _, test_tree, test_scan = modules[0]
    test_node = _find_def(test_tree, qualname)
    if test_node is None:
        return {}, False
    queue = _requested_names(test_node, test_scan)
    if "." in qualname:  # class-level usefixtures apply to the method
        cls = _find_def(test_tree, qualname.rsplit(".", 1)[0])
        for dec in getattr(cls, "decorator_list", []) if cls is not None else []:
            queue |= _usefixtures_names(dec, test_scan)
    for _, _, m in modules:
        queue |= m.autouse | m.mark_names

    comps: dict[str, str] = {}
    seen: set[str] = set()
    while queue:
        name = queue.pop()
        if name in seen or name in _FIX_SKIP:
            continue
        seen.add(name)
        for rel, _, m in modules:  # nearest wins, like pytest's lookup
            node = m.fixtures.get(name)
            if node is not None:
                comps[f"{name}@{rel}"] = _node_hash(node)
                queue |= _requested_names(node, m)
                break
    return comps, any(m.dynamic for _, _, m in modules)


def _fixture_suffix(root: Path, path_str: str, qualname: str, cache: dict) -> str:
    """The fixture-closure component of one node id's hash part.

    '' when the test resolves no project fixtures — such parts stay byte-
    identical to the pre-coverage format, so their keys never move on
    upgrade. ';fixtures:...' lists each resolved def, sorted.
    ';fixturechain:...' hashes the whole module + conftest chain whenever
    fixture use is dynamic or the walk fails — degrade to sound, never
    silently narrower. Never raises.
    """
    chain = _chain_paths(root, path_str)
    if not chain:
        return ""
    try:
        comps, dynamic = _resolve_fixtures(chain, qualname, cache)
    except Exception:  # noqa: BLE001 — unparseable conftest, walk surprise: degrade
        comps, dynamic = {}, True
    if dynamic:
        return ";fixturechain:" + ",".join(f"{rel}={_file_hash(p)}" for rel, p in chain)
    if not comps:
        return ""
    return ";fixtures:" + ",".join(f"{k}={v}" for k, v in sorted(comps.items()))


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

    Each test's *fixture closure* is in the hash too: the fixtures it requests
    (arguments, usefixtures marks, literal getfixturevalue), autouse fixtures
    in scope, and fixtures of fixtures, statically resolved through the test's
    module and conftest chain, nearest first — so editing only a conftest
    fixture busts exactly the tests that lean on it. Fixture use the walk
    cannot resolve degrades to hashing the whole chain (see _fixture_suffix).

    Limitation: plain helper functions a test imports and calls are still not
    covered — only the fixture graph is.
    """
    parts = []
    fixture_cache: dict = {}  # parsed modules, shared across this call's node ids
    for nid in sorted(node_ids):
        path_str, _, rest = nid.partition("::")
        qualname = ".".join(seg.split("[", 1)[0] for seg in rest.split("::")) if rest else ""
        h = None
        fix = ""
        if qualname:
            try:
                h = _hash_def(root, path_str, qualname)
                fix = _fixture_suffix(root, path_str, qualname, fixture_cache)
            # OSError/ValueError cover unreadable and non-UTF-8 files — the
            # degrade-to-id promise holds even for sources we cannot decode
            except (HashloomError, OSError, ValueError):
                h = None
        parts.append(f"{nid}={h or 'id'}{fix}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
