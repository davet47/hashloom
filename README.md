# heddle

[![CI](https://github.com/davet47/heddle/actions/workflows/ci.yml/badge.svg)](https://github.com/davet47/heddle/actions/workflows/ci.yml)

![heddle regenerating a unit: one ~300-token context packet plus a cached verification, instead of re-reading whole files](https://raw.githubusercontent.com/davet47/heddle/main/docs/demo.gif)

**Heddle treats software units as content-addressed contracts rather than files.** An MCP server that makes agent regeneration loops cheap.

Because contracts are content-addressed and dependency-aware, agents reuse verification, compute blast radius precisely, and regenerate code from a few hundred tokens of context instead of re-reading whole files. Build systems ask which files changed. Heddle asks which software obligations changed.

The heddle is the part of a loom that holds the warp threads, the fixed, durable strands, while the shuttle weaves disposable weft through them. **Contracts are warp. Code is weft.**

## The problem

Agents repeatedly pay to rediscover software structure. Spec-driven development tools made specs the durable artifact and code regenerable, but they run on plain files, so every regeneration loop re-derives what the project already knows:

1. **Context acquisition is expensive.** Regenerating one unit means re-reading whole spec and source files: thousands of tokens to learn what a few hundred convey.
2. **Verification is uncached.** Every regeneration re-runs (and re-reads the output of) the full relevant test surface, even for units whose contracts haven't changed.
3. **Blast radius is by convention, not mechanism.** When a spec changes, nothing tells the agent precisely which dependents are invalidated.

## The model

Heddle treats each software unit as a content-addressed contract with explicit dependencies, not a file. A contract is a small YAML spec (signature, invariants, examples, dependency names); the implementation behind it is regenerable weft. Because every contract is hashed and its dependencies are named, the structure an agent keeps re-deriving from files becomes something heddle computes once and serves.

## Outcomes

The model buys three things, all mechanical:

- **Verification caching.** A green test result is keyed on the contract, implementation, and dependency hashes, and served from cache until one of them changes. pytest runs only on a real miss.
- **Mechanical blast radius.** A contract change reports the exact set of invalidated dependents, transitively and by hash, not by convention.
- **Tiny context packets.** An agent regenerating a unit gets the contract, its dependencies' signatures, and its callers as one packet of a few hundred tokens, instead of the whole file closure.

### The number

Same three regeneration tasks on a 20-contract sample project, once with raw file reads, once through heddle (tiktoken cl100k, reproduce with `uv run python bench/benchmark.py`):

| task                | raw files | heddle | reduction |
|---------------------|----------:|-------:|----------:|
| revenue_by_region   |     1,925 |    369 |      5.2x |
| top_customers       |     2,137 |    337 |      6.3x |
| revenue_by_category |     1,942 |    396 |      4.9x |
| **total**           | **6,004** | **1,102** | **5.4x** |

Raw mode counts what a file-based agent reads per task: the unit's spec file, every transitive dep's spec file, every source module in the dep closure, the unit's test file, and the output of running the suite. It is deliberately generous to the baseline: it assumes the agent already knows the exact dependency closure, which is precisely the thing heddle computes for you.

## Quickstart

```bash
pip install heddle-mcp
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
status: inferred        # reverse-engineered, not yet human-reviewed; omit once confirmed
```

Subdirectories are namespaces: `contracts/billing/invoice.yaml` is the contract
`billing/invoice`, so the same short name can live in different folders. A
contract's `name` must match its path under `contracts/`.

### When to write a contract

A contract belongs on a stable seam: an interface other units depend on and that you expect to outlive its current implementation. The implementation behind it is disposable weft, regenerated freely. Dropping a contract where it does not earn that place is correct use, not a failure. The failure mode is the opposite, over-pinning interiors you would happily rewrite, which turns the durable layer into busywork.

Contracts are reviewed artifacts. Authoring one is cheap and getting cheaper, so the real cost is reviewing it, not writing it. A wrong contract is worse than no contract, because the durable artifact now lies: agents will regenerate code to satisfy a spec that is itself incorrect. Review a contract the way you review an interface, not the way you skim generated code.

A contract an agent reverse-engineers from existing code can declare that it hasn't earned that review yet: `status: inferred`. Tools then flag — never refuse — any blast-radius or verification answer that rests on it (`inferred: true` on dependents, an `inferred` list on verify results, a review queue in `status`). Absent means `confirmed`, and confirming an inferred contract after review is free: status is provenance, not meaning, so the flip invalidates nothing.

### Hashing semantics

- **Contract hash**: sha256 over a canonical form: keys sorted, whitespace normalised, comments stripped, example order preserved, dep order ignored. `impl`, `tests`, `invariants`, and `status` are excluded, so **relocating files never invalidates**, rewording an invariant is free, and confirming an inferred contract never invalidates anything. Invariants are documentation, not a machine obligation; the real check is the tests, whose source is in the verification key.
- **Impl hash**: sha256 over the normalised AST of the implementation, so reformatting and comment edits never bust the cache. Docstrings are stripped too.
- **Verification key**: `(contract hash, impl hash, test-source hash, toolchain identity, transitive dep contract hashes)`. Heddle caches verification results, keyed so that a change to any contract in the closure, to the implementation, to a test's own source, or to the toolchain version forces a re-run. The toolchain component (`python 3.11.7`, `go 1.21.5`, `node <v> ts <v>`) is what makes a shared or cross-machine green sound: a 3.11 pass is never served to 3.13. Failures are never served from cache. Two caveats. A cached pass assumes deterministic tests, so a green result that depended on wall-clock time, network, or randomness can outlive the condition that made it pass. And the test-source hash covers each test function's own normalised AST, not the conftest fixtures or helpers it calls, so changing only those will not force a re-run yet (see [Roadmap](ROADMAP.md)).

## MCP tools (the entire surface)

| tool | does |
|---|---|
| `get_contract` | the ~300-token context packet: contract + hash + one-line dep signatures + caller list |
| `put_contract` | validate, write `contracts/<name>.yaml`, return new hash, a semantic diff of what changed, and every invalidated dependent |
| `get_dependents` | blast-radius query, direct or transitive, names + hashes; inferred (unreviewed) contracts flagged |
| `verify` | per-unit `cached-pass` / `pass` / `fail` plus a top-level `ok` gate bit; `radius=true` widens each name to its full blast radius; runs tests only on cache misses; failures come back as a ≤40-token assertion summary, never a traceback; inferred contracts in the closure flagged |
| `status` | dirty contracts, stale verifications, cache hit-rate, resolved verify interpreter, cumulative token counters |

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

### Beyond Python

The impl's file extension picks the language adapter — each brings a
normalised-AST hasher and a test runner, so the same cosmetic-vs-meaning hashing
semantics hold per language:

- **Go** (`.go`): hashes via the stdlib `go/ast`, runs `go test -json`. Toolchain
  resolves like the interpreter: `.heddle/config.json` `{"go": "..."}`, else `go`
  on PATH.
- **TypeScript** (`.ts`/`.tsx`/`.mts`/`.cts`): hashes via the target project's
  *own* `typescript` compiler API, auto-detects the test runner from
  `package.json` (vitest / jest, else Node's built-in `node:test`). Needs Node
  >= 22.6; config key `{"node": "..."}`.

Python stays the default; a project can mix languages freely.

### Team-shared verification cache

By default the cache lives in your local `.heddle/store.db`. Point it at a shared
backend and one green verify serves the whole team — CI verifies a unit once and
every teammate's agent gets `cached-pass`:

```jsonc
// .heddle/config.json
{"shared": {"url": "https://cache.internal:8770", "token": "..."}}
```

Run the backend anywhere with `python -m heddle.cache_server` (a small
bearer-token HTTP service over a SQLite store; an operational process, not a CLI
command). Only greens are published — failures never cross the boundary — and the
toolchain-in-key rule above keeps a shared green sound across machines. If the
shared store is unreachable, verify degrades silently to local.

## CLI

`heddle init` · `heddle index` · `heddle serve` · `heddle status` · `heddle verify`. The sqlite store under `.heddle/` is derived state: delete it any time and `heddle index` rebuilds it from `contracts/`.

`heddle verify <name>…` runs the same cached verification as the MCP tool from the command line and exits nonzero unless every unit is green (a failure, an unknown name, or an unverifiable unit all block) — drop it in CI or a pre-commit hook. `--radius` widens each name to itself plus every transitive dependent, so one command gates a change's whole blast radius: `heddle verify --radius Sale`.

## Try the sample project

```bash
cd examples/sales
heddle init && heddle index && heddle serve   # then point your agent at it
```

20 contracts, 25 tests, three dependency layers deep.

## Development

```bash
uv sync
uv run pytest             # full suite; hash stability is the load-bearing suite
uv run python bench/benchmark.py
```

Kept deliberately small: 5 MCP tools, 5 CLI commands, contracts as plain YAML. Everything not in this README is an [issue](ISSUES.md).

## License

Apache 2.0
