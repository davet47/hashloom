# heddle

[![CI](https://github.com/davet47/heddle/actions/workflows/ci.yml/badge.svg)](https://github.com/davet47/heddle/actions/workflows/ci.yml)

**Hash-keyed verification caching and content-addressed contracts for spec-driven development.** An MCP server that makes agent regeneration loops cheap.

The heddle is the part of a loom that holds the warp threads — the fixed, durable strands — while the shuttle weaves disposable weft through them. **Contracts are warp. Code is weft.**

## The number

Same three regeneration tasks on a 20-contract sample project, once with raw file reads, once through heddle (tiktoken cl100k, reproduce with `python bench/benchmark.py`):

| task                | raw files | heddle | reduction |
|---------------------|----------:|-------:|----------:|
| revenue_by_region   |     1,925 |    371 |      5.2x |
| top_customers       |     2,137 |    334 |      6.4x |
| revenue_by_category |     1,942 |    392 |      5.0x |
| **total**           | **6,004** | **1,097** | **5.5x** |

Raw mode counts what a file-based agent reads per task: the unit's spec file, every transitive dep's spec file, every source module in the dep closure, the unit's test file, and the output of running the suite. It is deliberately generous to the baseline — it assumes the agent already knows the exact dependency closure, which is precisely the thing heddle computes for you.

## Why

Spec-driven development tools made specs the durable artifact and code regenerable — but they run on plain files:

1. **Context acquisition is expensive.** Regenerating one unit means re-reading whole spec and source files: thousands of tokens to learn what a few hundred convey.
2. **Verification is uncached.** Every regeneration re-runs (and re-reads the output of) the full relevant test surface, even for units whose contracts haven't changed.
3. **Blast radius is by convention, not mechanism.** When a spec changes, nothing tells the agent precisely which dependents are invalidated.

Heddle fixes this with a content-addressed contract store and a hash-keyed verification cache, exposed over MCP so any agent workflow can use it.

## Quickstart

```bash
pip install heddle
# or from source: pip install "git+https://github.com/davet47/heddle"

cd your-project
heddle init                 # creates .heddle/ and contracts/
heddle index                # builds the store from contracts/
```

Point Claude Code at it:

```bash
claude mcp add heddle -- heddle serve
```

(Stdio transport; the server resolves the project by walking up from its working directory to the nearest `.heddle/`.)

## Contracts

One YAML file per unit in `contracts/`. Minimal, hand-writable, hashable:

```yaml
name: revenue_by_region
signature: "(sales: list[Sale]) -> dict[Region, float]"
deps: [Sale, Region]            # other contract names
invariants:
  - excludes sales where completed is false
  - excludes sales with null amount
examples:
  - in:  "[Sale(region='QLD', amount=10, completed=True)]"
    out: "{'QLD': 10.0}"
tests: [tests/test_revenue.py::test_revenue_by_region]   # pytest node IDs
impl: src/revenue.py::revenue_by_region                  # current woven weft
```

### Hashing semantics

- **Contract hash** — sha256 over a canonical form: keys sorted, whitespace normalised, comments stripped, invariant/example order preserved (order is meaning), dep order ignored. `impl` and `tests` are excluded: **relocating files never invalidates.**
- **Impl hash** — sha256 over the normalised AST of the implementation, so reformatting and comment edits never bust the cache. Docstrings are stripped too.
- **Verification key** — `(contract hash, impl hash, transitive dep contract hashes)`. A cached green result is served iff the full key matches; an edit to any contract in the closure forces a re-run. Failures are never served from cache.

## MCP tools (the entire surface)

| tool | does |
|---|---|
| `get_contract` | the ~300-token context packet: contract + hash + one-line dep signatures + caller list |
| `put_contract` | validate, write `contracts/<name>.yaml`, return new hash + every invalidated dependent |
| `get_dependents` | blast-radius query, direct or transitive, names + hashes |
| `verify` | per-unit `cached-pass` / `pass` / `fail`; runs pytest only on cache misses; failures come back as a ≤40-token assertion summary, never a traceback |
| `status` | dirty contracts, stale verifications, cache hit-rate, cumulative token counters |

Every tool returns structured errors — `{"error": {"code": "unknown_dep", "message": "'Regoin' not found — nearest: 'Region'"}}` — never a stack trace.

### The verify interpreter

`verify` runs your tests with the project's own python, resolved in order:
`heddle serve --python PATH` → `.heddle/config.json` (`{"python": "..."}`) → an
auto-detected `<project>/.venv` → the interpreter running heddle. So a
globally-installed heddle can verify a project against its own virtualenv without
being installed into it; `heddle status` shows which interpreter it resolved.

`.heddle/config.json` also takes `verify_timeout` (seconds per pytest run,
default 300) for suites that need longer than the default, and `pycache_trust`
(default `true`); set `pycache_trust: false` — or pass `--no-pycache-trust` — to
clear the project's `__pycache__` before each verify run, so a stale `.pyc` can
never shadow the current source.

## CLI

`heddle init` · `heddle index` · `heddle serve` · `heddle status` · `heddle verify`. The sqlite store under `.heddle/` is derived state: delete it any time and `heddle index` rebuilds it from `contracts/`.

`heddle verify <name>…` runs the same cached verification as the MCP tool from the command line and exits nonzero if any unit fails — drop it in CI or a pre-commit hook.

## Try the sample project

```bash
cd examples/sales
heddle init && heddle index && heddle serve   # then point your agent at it
```

20 contracts, 25 tests, three dependency layers deep.

## Development

```bash
uv sync
uv run pytest             # 46 tests; hash stability is the load-bearing suite
uv run python bench/benchmark.py
```

Python-only and single-process by design for v0.1. Everything not in this README is an [issue](ISSUES.md).

## License

Apache 2.0
