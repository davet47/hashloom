# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- A benchmark scorecard, `docs/benchmarks.md`, and a full-sweep benchmark,
  `bench/sweep.py`: the scorecard holds every published token-reduction
  number — the sales DoD gate (5.4×) plus full sweeps of all three example
  projects (sales 4.1×, go-ledger 3.0×, ts-cart 3.1× — sweeps count the leaf
  units the gate doesn't, so they average lower by construction), the
  dogfood store's cache counters, and the concessions any public claim
  should carry (closure knowledge granted free to the baseline;
  first-try-green assumed for heddle; per-change estimate, not a session
  total; initial build costs more). `sweep.py` runs the same accounting over
  every verifiable unit of any heddle project, language-aware only in the
  suite runner (pytest / `go test` / `node --test`). Every scorecard row is
  reproducible from this repo alone; ratios are deterministic tiktoken
  counts and independent of what drives the session. The README's "The
  number" section links to it.

## [0.3.0] - 2026-07-04

Theme: adoption. Everything a first-time visitor needs that the engine
releases didn't ship: a getting-started walkthrough for the contract-first
agent workflow, sample projects in all three supported languages, and the
strongest possible existence proof — heddle developing heddle, its own stable
seams under contract (written `inferred` by the agent, since reviewed and
explicitly confirmed by a human, at zero re-verification cost). No code
changes: the engine is 0.2.0's; the 5 MCP tools / 5 CLI commands surface and
all response shapes are unchanged.

### Added
- Heddle develops on heddle: the repo is now itself a heddle project —
  `contracts/` holds 12 contracts over the stable seams (the five `api.py`
  tool functions, the hashing trio, `impl_hash`, `verification_key`,
  `HeddleError`, the `Store` Protocol), bound to the existing test suite and
  born `status: inferred` pending human review. `heddle verify --radius` is
  the inner-loop gate for changes to contracted seams; the full pytest suite
  and the benchmark remain the definition of done.
- A getting-started walkthrough, `docs/getting-started.md`: how a human and an
  agent build a package contract-first — setup, the CLAUDE.md working rules to
  give the agent, the inferred→confirmed review loop, and the `verify --radius`
  gate as the definition of done.
- A TypeScript sample project, `examples/ts-cart`: 8 contracts over a shopping
  cart (interface/type-alias contracts included), exercising the TypeScript
  adapter end to end — canonical-AST impl hashing via the project's own
  `typescript`, `node:test` verification under type stripping, and the
  `verify --radius` gate.
- A Go sample project, `examples/go-ledger`: 8 contracts over a small
  double-entry ledger (struct/type contracts included), exercising the Go
  adapter end to end — AST-stable impl hashing, `go test -json` verification,
  and the `verify --radius` gate.

## [0.2.0] - 2026-07-04

Theme: solo → team. A team can now share verification greens — one teammate or
CI verifies a unit once and everyone gets `cached-pass` — soundly, keyed by
toolchain. Plus two new language adapters, contract provenance, and a
CI-gateable verify. Everything is additive: the 5 MCP tools / 5 CLI commands
surface and the contract format are unchanged, and 0.1.0 projects work as-is.
One-time cost on upgrade: existing cached greens re-verify once (the
verification key now includes the toolchain).

### Added
- Gate-shaped verification: `verify` responses carry a top-level `ok` — true iff
  every unit is `pass`/`cached-pass` (failures, unknown names, and unverifiable
  units all gate) — and a `radius` option (`heddle verify --radius NAME`, MCP
  `verify(names, radius=true)`) widens each name to itself plus every transitive
  dependent, spec-only units dropped. One call = a hard pass/fail for a change's
  whole blast radius; the CLI exit code mirrors `ok`, so a CI step or agent loop
  can block on it. No new tools/commands.
- Contract provenance: an optional `status: inferred | confirmed` field on
  contracts. `inferred` marks a contract reverse-engineered from code and not
  yet human-reviewed; tools warn — never refuse — when a decision rests on one
  (`inferred: true` on `get_dependents`/`get_contract` dep entries, `inferred`
  and `invalidated_inferred` on `put_contract`, an `inferred` list on `verify`
  results, and a review-queue list in `status`). Absent = `confirmed`, so
  existing contracts are unaffected, and the field is excluded from the contract
  hash, so confirming an inferred contract after review invalidates nothing and
  busts no cached green. The 5-tool / 5-CLI surface is unchanged; every new
  response key appears only when an inferred contract is actually involved.
- Remote shared verification cache (transport): a `RemoteStore` client and a
  stdlib `python -m heddle.cache_server` (a bearer-token JSON HTTP service over a
  `SqliteStore`) let a team share verdicts and impl blobs across machines —
  configured per project via `.heddle/config.json` `{"shared": {"url","token"}}`,
  with **no change to the 5 MCP tools / 5 CLI commands** (the cache server is an
  operational process, not a subcommand). A shared-store outage degrades silently
  to local verify. Cross-machine greens are made sound by the toolchain-in-key
  change below.
- Toolchain in the verification key: the key now folds in a per-language toolchain
  identity (`python 3.11.7` / `go 1.21.5` / `node <v> ts <v>`), so a shared or
  cross-machine green is trusted only when the toolchain version matches —
  otherwise it re-runs. Version-only (no OS/arch), so a CI(Linux) green still
  serves a Mac/Windows dev. One-time: existing greens re-verify once on upgrade.
- Semantic diff in `put_contract`: the response carries a `diff` of what changed
  versus the prior contract (signature, deps, invariants, examples, impl/tests).
- Test source in the verification key (#18): editing a test's body now forces a
  re-run; reformatting, comments, and docstrings in a test stay cached. Conftest
  fixtures and helpers a test calls are not yet covered.
- Content-addressed impl-source store: `heddle index` stores each impl file's
  source as a deduped blob, so the store can serve weft, not only verdicts.
- A backend-agnostic `Store` interface (a Protocol) with `SqliteStore` as the
  local implementation: the seam for a shared/remote cache.
- Shared verification cache MVP (`LayeredStore`): a local store fronted by a
  shared one (read-through, write-through for greens), so one client's verified
  green serves another. Design for the hosted service in docs/hosted-store.md.
- Multi-language adapters: contracts whose `impl` is a `.go` file verify with a
  Go adapter (a stdlib `go/ast` hash helper plus `go test -json`), chosen by the
  impl's extension. Python is unchanged and the default; the contract syntax and
  the 5-tool / 5-CLI surface are unchanged.
- TypeScript adapter: contracts whose `impl` is a `.ts`/`.tsx`/`.mts`/`.cts` file
  verify with a TypeScript adapter — a hand-written canonical AST hash via the TS
  Compiler API (resolved from the project's own `typescript`, since TS has no
  `ast.dump`), plus an auto-detected test runner (vitest / jest if declared in
  `package.json`, else Node's built-in `node:test`). Needs Node (>= 22.6 for `.ts`
  type-stripping under `node:test`). Python and Go are unchanged; the contract
  syntax and the 5-tool / 5-CLI surface are unchanged.
- A `rechecks` block in `status` (#20): re-verifications triggered by a contract
  change, and how many changed no verdict (`wasted_rate`).
- Invariants out of the contract hash (#19): rewording or reordering an invariant
  no longer changes the hash or cascades a re-verify. Invariants are documentation;
  the machine check is the tests (their source is in the key via #18). One-time:
  contracts with invariants re-hash once on upgrade.

## [0.1.0] - 2026-06-23

First public release, published to PyPI as `heddle-mcp` (the import name and CLI
stay `heddle`).

### Added
- Content-addressed contracts: one hashable YAML file per software unit
  (signature, invariants, examples, dependencies), with subdirectory namespaces.
- Hash-keyed verification cache: a green test result keyed on the contract,
  implementation, and transitive dependency hashes. pytest runs only on a miss;
  failures are never served from cache.
- Mechanical blast radius: `get_dependents` reports the exact set of invalidated
  dependents, direct or transitive, by hash.
- Five MCP tools (`get_contract`, `put_contract`, `get_dependents`, `verify`,
  `status`) and five CLI commands (`init`, `index`, `serve`, `status`, `verify`).
- Configurable verify interpreter and timeout via `heddle serve --python`,
  `.heddle/config.json`, or an auto-detected project `.venv`.
- `--no-pycache-trust` / `pycache_trust` to clear stale `__pycache__` before a
  verify run.
- Structured errors over MCP (no stack traces).
- CI (tests on Python 3.10 through 3.13 plus the >5x benchmark guard) and PyPI
  Trusted Publishing on version tags.

[Unreleased]: https://github.com/davet47/heddle/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/davet47/heddle/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/davet47/heddle/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/davet47/heddle/releases/tag/v0.1.0
