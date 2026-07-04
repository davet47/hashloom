# Roadmap

**v0.1 shipped 0.1.0 to PyPI as `heddle-mcp` on 2026-06-23.** It is the engine:
content-addressed contracts, a hash-keyed verification cache, and a blast-radius
query, over MCP, single-process and Python-only by design. What follows is where
it goes next. The deferred-by-design items live in [ISSUES.md](ISSUES.md); this
is the prioritization.

## Theme for v0.2: solo → team

The single highest-leverage move, and the one the spec already named "the obvious
v0.2 candidate."

### The one big thing — hosted / team-shared store

Today the verification cache is a per-developer `.heddle/store.db`. Make it
shared: a teammate or CI verifies `revenue_by_region` green once, and everyone
else gets `cached-pass` for free. This is the leverage multiplier and the
natural path to a hosted offering.

Progress: the `Store` interface (a Protocol) and a `LayeredStore` MVP (a local
store fronted by a shared one, read-through and write-through for verdicts and
blobs) are in, and one client's green already serves another in tests. The
remaining lift is the server backend; the design (transport, auth, concurrent
writers, cross-graph invalidation, trust, clocks) is in
[docs/hosted-store.md](docs/hosted-store.md).

### Supporting (ship alongside)

- ✓ **Semantic diff in `put_contract`** (shipped) — the response reports *what*
  changed in a contract, not just that it did and who it invalidated.
- ✓ **Content-addressed implementation store** (shipped) — `heddle index` stores
  each impl file's source as a deduped, content-addressed blob, so the store can
  serve weft, not only verdicts.

### Sharpening the verification model

Direction toward a sharper verification model along two axes, soundness and
precision, so the README can eventually claim more than "caches verification
results."

- ✓ **Test source in the verification key** ([#18](https://github.com/davet47/heddle/issues/18)) (shipped).
  The key now folds in a normalised-AST hash of each test's source, so a
  test-body edit forces a re-run. Conftest fixtures and helpers a test calls are
  not yet covered.
- ✓ **Invariants out of the binding hash** ([#19](https://github.com/davet47/heddle/issues/19)) (shipped).
  Invariants are now excluded from the contract hash, so rewording one no longer
  cascades a re-verify; the machine check is the tests (their source is in the
  key via #18). A meaning-changing invariant edit will not re-verify; invariants
  are prose, and this is a precision fix, not a soundness one.
- ✓ **Semantic necessity rate in `status`** ([#20](https://github.com/davet47/heddle/issues/20)) (shipped).
  `status` reports a `rechecks` block: re-verifications triggered by a hash bust
  and how many changed no verdict (`wasted_rate`), measuring how much
  re-verification is cosmetic.
- ✓ **Contract provenance** (shipped): `status: inferred | confirmed` marks
  whether a contract has been human-reviewed; tools warn (never refuse) when a
  blast-radius or verification answer rests on an inferred contract. Absent =
  confirmed; excluded from the hash, so confirming is free. A strict mode that
  refuses instead of warns is deferred by design.

## v0.3+ — bigger bets

- **Multi-language** — a normalised-AST hasher + a test-runner adapter per
  language, behind a per-language adapter seam chosen by the impl extension.
  ✓ **Go shipped** (stdlib `go/ast` hash + `go test -json`) and ✓ **TypeScript
  shipped** (hand-written canonical AST hash via the TS Compiler API, plus an
  auto-detected runner: vitest / jest / Node's built-in `node:test`); Python is
  the default. Each further language is real work.
- **Tessl spec-format compatibility** — an import/export adapter, once that format
  is stable.

## Pre-1.0 polish

The `launch-polish` pass (#17) shipped in 0.1.0: dropped the hard test count from
the README, added `heddle --version`, single-sourced the version via hatchling,
fixed the benchmark command to `uv run python`, added `src/heddle/py.typed`,
surfaced the resolved interpreter and the Repository/Issues URLs, and cleaned up
the packaging metadata.

Still open (post-launch):

- A single error-code naming convention (`bad_*` vs `invalid_*`).

## Explicitly not doing

No new contract syntax — contracts stay plain YAML. Guarding this is how the
project avoids "scope creep toward Loom." Keep the surface minimal: 5 MCP tools,
5 CLI commands.

## Suggested sequencing

Shipped: v0.1 (PyPI, demo gif, announcements); v0.2 (semantic diff,
content-addressed impl store, the `Store` interface, the shared-cache MVP); the
**Go** and **TypeScript** adapters; and the verification-model sharpening
(#18, #19, #20). Next, in rough order:

1. **Hosted-store server**: turn the `LayeredStore` MVP into a real shared
   backend (transport, auth, cross-graph invalidation); design in
   [docs/hosted-store.md](docs/hosted-store.md).
2. **Tessl compatibility**, and the post-launch error-code naming convention
   (`bad_*` vs `invalid_*`).
