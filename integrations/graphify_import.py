"""Bootstrap hashloom contracts from a graphify knowledge graph.

Reads the graph.json that `graphify extract` writes (graphify-out/graph.json)
and emits skeleton contracts — all `status: inferred` — for an explicitly
chosen set of units. The graph supplies structure (impl location, deps from
EXTRACTED edges, candidate test node ids); signatures are read from the Python
source itself, and invariants and examples are left for the human review pass.
One-shot generation: the graph is never a runtime data source.

    uv run python integrations/graphify_import.py graphify-out/graph.json --root . --list
    uv run python integrations/graphify_import.py graphify-out/graph.json --root . \
        --units src/metrics.py::revenue_by_region src/types.py::Sale

Python impls only; nodes for other languages are skipped with a warning.
After a successful run: `hashloom index && hashloom status` — the new
contracts land in the inferred review queue.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from hashloom.contract import parse_contract  # noqa: E402
from hashloom.errors import HashloomError  # noqa: E402

# edge relations that express "depends on" between units; everything else
# (imports, contains, method, defines, indirect_call, ...) is file-granularity
# noise or dynamic-dispatch guessing here
DEP_RELATIONS = {"calls", "references", "inherits", "implements", "extends"}


def warn(msg: str) -> None:
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------- graph side


@dataclass
class Node:
    node_id: str
    qualname: str  # label with trailing () and leading . stripped, e.g. "Sale" or "add"
    source_file: str
    line: int | None
    is_callable: bool  # label carried trailing ()
    is_method: bool  # label carried a leading . (graphify methods are ".name()")


@dataclass
class Graph:
    nodes: dict[str, Node]
    edges: list[dict]


def load_graph(path: Path) -> Graph:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"error: cannot read graph '{path}': {e}")
    # graphify writes NetworkX node-link JSON: released versions use "links",
    # the v8 build step renames it to "edges" — accept both
    edges = data.get("edges", data.get("links")) if isinstance(data, dict) else None
    if not isinstance(data, dict) or "nodes" not in data or edges is None:
        raise SystemExit(
            f"error: '{path}' does not look like a graphify graph.json "
            "(expected top-level 'nodes' and 'edges'/'links')"
        )
    nodes: dict[str, Node] = {}
    for n in data["nodes"]:
        if n.get("file_type") != "code" or not n.get("source_file"):
            continue
        loc = n.get("source_location")
        line = int(loc[1:]) if isinstance(loc, str) and loc.startswith("L") else None
        if line is None:
            continue
        label = str(n.get("label", ""))
        if label == Path(n["source_file"]).name:
            continue  # file-level node, not a unit
        is_callable = label.endswith("()")
        qualname = label[:-2] if is_callable else label
        is_method = qualname.startswith(".")  # graphify methods have no class in the label
        qualname = qualname.lstrip(".")
        if not qualname:
            continue
        nodes[n["id"]] = Node(n["id"], qualname, n["source_file"], line, is_callable, is_method)
    return Graph(nodes, list(edges))


def is_test_path(source_file: str) -> bool:
    p = Path(source_file)
    return "tests" in p.parts or p.name.startswith("test_") or p.stem.endswith("_test")


def is_python(source_file: str) -> bool:
    return source_file.endswith(".py")


# ---------------------------------------------------------------- source side


@dataclass
class Unit:
    node: Node
    kind: str = "function"  # function | method | class (AST-confirmed)
    qualname: str = ""  # AST-confirmed (falls back to the node's label qual)
    signature: str = ""
    deps: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)

    @property
    def contract_name(self) -> str:
        return self.qualname

    @property
    def impl(self) -> str:
        return f"{self.node.source_file}::{self.qualname}"


def _defs_with_quals(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    """Every function/class def in the module with its dotted qualname."""
    out: list[tuple[str, ast.AST]] = []

    def visit(body: list, prefix: str) -> None:
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}.{n.name}" if prefix else n.name
                out.append((qual, n))
                visit(n.body, qual)

    visit(tree.body, "")
    return out


def _resolve_def(tree: ast.Module, node: Node) -> tuple[str, ast.AST, str | None]:
    """Find the def for a graph node: by line first, then by name.

    Returns (qualname, ast node, warning-or-None); raises LookupError when
    neither strategy matches.
    """
    defs = _defs_with_quals(tree)
    for qual, d in defs:
        first = min((dec.lineno for dec in d.decorator_list), default=d.lineno)
        # tree-sitter may report the decorator line where CPython reports the def
        if first <= node.line <= d.lineno:
            return qual, d, None
    by_name = [(q, d) for q, d in defs if q == node.qualname]
    if not by_name:
        by_name = [(q, d) for q, d in defs if q.rsplit(".", 1)[-1] == node.qualname]
    if len(by_name) == 1:
        qual, d = by_name[0]
        return qual, d, (
            f"line L{node.line} did not match a def in {node.source_file} "
            f"(graph may be stale; re-run graphify extract) — resolved '{qual}' by name"
        )
    raise LookupError(
        f"no def at L{node.line} in {node.source_file} and name "
        f"'{node.qualname}' is {'ambiguous' if by_name else 'absent'} "
        "(graph may be stale; re-run graphify extract)"
    )


def _render_args(args: ast.arguments, drop_first: bool = False) -> str:
    def one(a: ast.arg, default: ast.expr | None) -> str:
        s = a.arg
        if a.annotation is not None:
            s += f": {ast.unparse(a.annotation)}"
        if default is not None:
            s += f" = {ast.unparse(default)}"
        return s

    positional = list(args.posonlyargs) + list(args.args)
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    if drop_first and positional:
        positional, defaults = positional[1:], defaults[1:]
    parts = [one(a, d) for a, d in zip(positional, defaults)]
    if args.vararg is not None:
        parts.append("*" + one(args.vararg, None))
    elif args.kwonlyargs:
        parts.append("*")
    parts += [one(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults)]
    if args.kwarg is not None:
        parts.append("**" + one(args.kwarg, None))
    return ", ".join(parts)


def _is_dataclass_decorated(d: ast.ClassDef) -> bool:
    for dec in d.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
        if name == "dataclass":
            return True
    return False


def build_signature(defn: ast.AST, qual: str) -> tuple[str, str]:
    """Return (signature string, kind) in the style of hand-written contracts."""
    if isinstance(defn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        kind = "method" if "." in qual else "function"
        sig = f"({_render_args(defn.args, drop_first=kind == 'method')})"
        if defn.returns is not None:
            sig += f" -> {ast.unparse(defn.returns)}"
        return sig, kind
    assert isinstance(defn, ast.ClassDef)
    name = defn.name
    if _is_dataclass_decorated(defn):
        fields = [
            ast.unparse(n.target)
            + f": {ast.unparse(n.annotation)}"
            + (f" = {ast.unparse(n.value)}" if n.value is not None else "")
            for n in defn.body
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        ]
        return f"dataclass: {name}({', '.join(fields)})", "class"
    init = next(
        (n for n in defn.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
        None,
    )
    if init is not None:
        return f"class: {name}({_render_args(init.args, drop_first=True)})", "class"
    return f"class: {name}", "class"


# -------------------------------------------------------------- derivations


def derive_deps(graph: Graph, unit: Unit, selected: dict[str, Unit]) -> list[str]:
    """Targets of EXTRACTED dep-relation edges into other selected units."""
    deps = set()
    for e in graph.edges:
        if (
            e.get("source") == unit.node.node_id
            and e.get("confidence") == "EXTRACTED"
            and e.get("relation") in DEP_RELATIONS
            and e.get("target") in selected
            and e.get("target") != unit.node.node_id
        ):
            deps.add(selected[e["target"]].contract_name)
    return sorted(deps)


def _test_qual(root: Path, node: Node, cache: dict[str, ast.Module | None]) -> str:
    """Full dotted qualname of a test function.

    Method labels carry no class ("`.test_x()`"), so the pytest node id's
    `TestCls::test_x` part is only recoverable from the source; fall back to
    the label's name when the file won't parse or the line went stale.
    """
    if node.source_file not in cache:
        try:
            cache[node.source_file] = ast.parse((root / node.source_file).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            cache[node.source_file] = None
    tree = cache[node.source_file]
    if tree is not None:
        try:
            qual, _, _ = _resolve_def(tree, node)
            return qual
        except LookupError:
            pass
    return node.qualname


def derive_tests(root: Path, graph: Graph, unit: Unit, tree_cache: dict) -> list[str]:
    """Pytest node ids for EXTRACTED calls into the unit from test functions."""
    tests = set()
    for e in graph.edges:
        if (
            e.get("target") != unit.node.node_id
            or e.get("confidence") != "EXTRACTED"
            or e.get("relation") != "calls"
        ):
            continue
        src = graph.nodes.get(e.get("source"))
        if src is None or not is_test_path(src.source_file) or not src.is_callable:
            continue
        qual = _test_qual(root, src, tree_cache)
        # last qualname segment must be a collectible test, not a helper
        if not qual.rsplit(".", 1)[-1].startswith("test"):
            continue
        tests.add(f"{src.source_file}::{qual.replace('.', '::')}")
    return sorted(tests)


# ------------------------------------------------------------------ emission


def render_contract(unit: Unit) -> str:
    lines = [f"name: {unit.contract_name}", f'signature: "{unit.signature}"']
    if unit.deps:
        lines.append(f"deps: [{', '.join(unit.deps)}]")
    if unit.tests:
        lines.append(f"tests: [{', '.join(unit.tests)}]")
    lines.append(f"impl: {unit.impl}")
    lines.append("status: inferred")
    return "\n".join(lines) + "\n"


def rank_candidates(graph: Graph) -> list[tuple[int, Node]]:
    """Candidate seams: non-test Python units, most-depended-on first."""
    candidates = {
        nid: n
        for nid, n in graph.nodes.items()
        if is_python(n.source_file) and not is_test_path(n.source_file)
    }
    counts = dict.fromkeys(candidates, 0)
    for e in graph.edges:
        src = graph.nodes.get(e.get("source"))
        if (
            e.get("target") in candidates
            and e.get("confidence") == "EXTRACTED"
            and e.get("relation") in {"calls", "references"}
            and src is not None
            and not is_test_path(src.source_file)
            and e.get("source") != e.get("target")
        ):
            counts[e["target"]] += 1
    ranked = sorted(
        candidates.values(),
        key=lambda n: (-counts[n.node_id], f"{n.source_file}::{n.qualname}"),
    )
    return [(counts[n.node_id], n) for n in ranked]


def resolve_selectors(selectors: list[str], graph: Graph) -> tuple[list[Node], list[str]]:
    """Map `src/foo.py::name` or bare `name` selectors to graph nodes."""
    by_ref = {f"{n.source_file}::{n.qualname}": n for n in graph.nodes.values()}
    picked: list[Node] = []
    errors: list[str] = []
    for sel in selectors:
        if "::" in sel:
            node = by_ref.get(sel)
            if node is None:
                errors.append(f"'{sel}' not found in the graph")
            else:
                picked.append(node)
            continue
        matches = [n for n in graph.nodes.values() if n.qualname == sel]
        if len(matches) == 1:
            picked.append(matches[0])
        elif not matches:
            errors.append(f"'{sel}' not found in the graph")
        else:
            forms = ", ".join(sorted(f"{n.source_file}::{n.qualname}" for n in matches))
            errors.append(f"'{sel}' is ambiguous — use one of: {forms}")
    return picked, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="graphify_import",
        description="Emit skeleton hashloom contracts (status: inferred) from a graphify graph.json.",
    )
    parser.add_argument("graph", metavar="GRAPH_JSON", help="path to graphify's graph.json")
    parser.add_argument("--root", required=True, metavar="DIR", help="hashloom project root (contracts/ lives here; graph paths resolve against it)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="rank candidate units by incoming dependency edges and exit")
    mode.add_argument("--units", nargs="+", metavar="SELECTOR", help="units to emit, as src/foo.py::name (see --list) or a unique bare name")
    parser.add_argument("--dry-run", action="store_true", help="print the contracts instead of writing them")
    parser.add_argument("--force", action="store_true", help="overwrite existing contracts/<name>.yaml files")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: --root '{args.root}' is not a directory", file=sys.stderr)
        return 1
    graph = load_graph(Path(args.graph))

    if args.list:
        for count, node in rank_candidates(graph):
            kind = ("method" if node.is_method else "function") if node.is_callable else "class"
            print(f"{count:>4}  {node.source_file}::{node.qualname}  {kind}")
        return 0

    picked, errors = resolve_selectors(args.units, graph)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 1

    # pass 1: resolve every selected node against the source; build the emit set
    units: dict[str, Unit] = {}  # node_id -> Unit
    skipped: list[tuple[Node, str]] = []
    for node in picked:
        if not is_python(node.source_file):
            skipped.append((node, "not a Python source file"))
            continue
        path = root / node.source_file
        if not path.is_file():
            print(f"error: '{node.source_file}' does not exist under {root}", file=sys.stderr)
            return 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            print(f"error: cannot parse '{node.source_file}' line {e.lineno}: {e.msg}", file=sys.stderr)
            return 1
        try:
            qual, defn, note = _resolve_def(tree, node)
        except LookupError as e:
            skipped.append((node, str(e)))
            continue
        if note:
            warn(f"warning: {note}")
        unit = Unit(node=node, qualname=qual)
        unit.signature, unit.kind = build_signature(defn, qual)
        units[node.node_id] = unit

    # pass 2: deps and tests over the final emit set only
    tree_cache: dict[str, ast.Module | None] = {}
    for unit in units.values():
        unit.deps = derive_deps(graph, unit, units)
        unit.tests = derive_tests(root, graph, unit, tree_cache)

    # in-set name collisions abort before anything is written
    by_name: dict[str, list[Unit]] = {}
    for unit in units.values():
        by_name.setdefault(unit.contract_name, []).append(unit)
    collisions = {name: us for name, us in by_name.items() if len(us) > 1}
    if collisions:
        for name, us in sorted(collisions.items()):
            forms = ", ".join(sorted(u.impl for u in us))
            print(f"error: name '{name}' collides across selected units: {forms}", file=sys.stderr)
        return 1

    # validate everything through the real parser, then check disk collisions
    rendered: dict[str, str] = {}
    for unit in units.values():
        text = render_contract(unit)
        try:
            parse_contract(text, expect_name=unit.contract_name)
        except HashloomError as e:
            print(f"error: generated contract for '{unit.contract_name}' is invalid ({e.code}): {e}", file=sys.stderr)
            return 1
        rendered[unit.contract_name] = text

    contracts_dir = root / "contracts"
    existing = [n for n in sorted(rendered) if (contracts_dir / f"{n}.yaml").exists()]
    if existing and not args.force:
        for n in existing:
            print(f"error: contracts/{n}.yaml already exists (use --force to overwrite, --dry-run to inspect)", file=sys.stderr)
        return 1

    for name in sorted(rendered):
        unit = by_name[name][0]
        summary = f"(deps: {', '.join(unit.deps) or '-'}; tests: {len(unit.tests)})"
        if args.dry_run:
            print(f"would emit contracts/{name}.yaml  {summary}")
            print(rendered[name])
        else:
            contracts_dir.mkdir(parents=True, exist_ok=True)
            (contracts_dir / f"{name}.yaml").write_text(rendered[name], encoding="utf-8")
            print(f"emitted   contracts/{name}.yaml  {summary}")
    for node, reason in skipped:
        print(f"skipped   {node.source_file}::{node.qualname}  — {reason}")

    print(f"\n{len(rendered)} contract{'s' if len(rendered) != 1 else ''} written, {len(skipped)} skipped. All are status: inferred.")
    if rendered and not args.dry_run:
        print("Next: hashloom index && hashloom status   # index picks them up; status shows the review queue")
    return 0 if rendered else 1


if __name__ == "__main__":
    raise SystemExit(main())
