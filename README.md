# heddle

[![CI](https://github.com/davet47/heddle/actions/workflows/ci.yml/badge.svg)](https://github.com/davet47/heddle/actions/workflows/ci.yml)

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
| revenue_by_region   |     1,925 |    371 |      5.2x |
| top_customers       |     2,137 |    334 |      6.4x |
| revenue_by_category |     1,942 |    392 |      5.0x |
| **total**           | **6,004** | **1,097** | **5.5x** |

Raw mode counts what a file-based agent reads per task: the unit's spec file, every transitive dep's spec file, every source module in the dep closure, the unit's test file, and the output of running the suite. It is deliberately generous to the baseline: it assumes the agent already knows the exact dependency closure, which is precisely the thing heddle computes for you.

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

Subdirectories are namespaces: `contracts/billing/invoice.yaml` is the contract
`billing/invoice`, so the same short name can live in different folders. A
contract's `name` must match its path under `contracts/`.

### When to write a contract

A contract belongs on a stable seam: an interface other units depend on and that you expect to outlive its current implementation. The implementation behind it is disposable weft, regenerated freely. Dropping a contract where it does not earn that place is correct use, not a failure. The failure mode is the opposite, over-pinning interiors you would happily rewrite, which turns the durable layer into busywork.

Contracts are reviewed artifacts. Authoring one is cheap and getting cheaper, so the real cost is reviewing it, not writing it. A wrong contract is worse than no contract, because the durable artifact now lies: agents will regenerate code to satisfy a spec that is itself incorrect. Review a contract the way you review an interface, not the way you skim generated code.

### Hashing semantics

- **Contract hash**: sha256 over a canonical form: keys sorted, whitespace normalised, comments stripped, invariant and example order preserved, dep order ignored. `impl` and `tests` are excluded, so **relocating files never invalidates.** Invariants are free text and live inside this hash, so rewording one without changing its meaning still moves the contract hash and re-verifies every dependent. Behaviour-equivalent prose edits are not free yet (see [Roadmap](https://github.com/davet47/heddle/blob/main/ROADMAP.md)).
- **Impl hash**: sha256 over the normalised AST of the implementation, so reformatting and comment edits never bust the cache. Docstrings are stripped too.
- **Verification key**: `(contract hash, impl hash, transitive dep contract hashes)`. Heddle caches verification results, not correctness: a cached green result is served iff the full key matches, and an edit to any contract in the closure forces a re-run. Failures are never served from cache. Two caveats are worth knowing. A cached pass assumes deterministic tests, so a green result that depended on wall-clock time, network, or randomness can outlive the condition that made it pass. And test source is not yet part of the key, so editing a test body without touching the contract or impl does not by itself force a re-run (see [Roadmap](ROADMAP.md)).

## MCP tools (the entire surface)

| tool | does |
|---|---|
| `get_contract` | the ~300-token context packet: contract + hash + one-line dep signatures + caller list |
| `put_contract` | validate, write `contracts/<name>.yaml`, return new hash + every invalidated dependent |
| `get_dependents` | blast-radius query, direct or transitive, names + hashes |
| `verify` | per-unit `cached-pass` / `pass` / `fail`; runs pytest only on cache misses; failures come back as a ≤40-token assertion summary, never a traceback |
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
uv run pytest             # full suite; hash stability is the load-bearing suite
uv run python bench/benchmark.py
```

Python-only and single-process by design for v0.1. Everything not in this README is an [issue](ISSUES.md).

## License

Apache 2.0
