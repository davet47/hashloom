# Roadmap

**Shipped so far** (full detail in the [CHANGELOG](CHANGELOG.md)):

- **v0.1** (0.1.0 → PyPI as `heddle-mcp`, 2026-06-23; the project renamed to
  `hashloom` in 0.4.0) — the engine:
  content-addressed contracts, a hash-keyed verification cache, and a
  blast-radius query, over MCP. Single-process and Python-only by design.
- **v0.2** (0.2.0 → PyPI, 2026-07-04) — solo → team: a shared verification
  cache (`LayeredStore` + `RemoteStore` + `python -m hashloom.cache_server`) with
  the toolchain folded into the verification key so cross-machine greens are
  sound; **Go** and **TypeScript** adapters behind the per-extension adapter
  seam; semantic diff in `put_contract`; test source in the key (#18);
  invariants out of the hash (#19); the `rechecks`/`wasted_rate` block in
  `status` (#20); contract provenance (`status: inferred | confirmed`); and
  gate-shaped verify (a hard `ok` bit plus `--radius`, so one call gates a
  change's whole blast radius).
- **v0.3** (0.3.0 → PyPI, 2026-07-04) — adoption: the
  [getting-started walkthrough](docs/getting-started.md) for the
  contract-first agent workflow; sample projects in all three languages
  (`examples/sales`, `examples/go-ledger`, `examples/ts-cart`); and hashloom
  developing hashloom — the repo's own stable seams under contract, reviewed and
  confirmed. No engine changes.
- **v0.5** (0.5.0 → PyPI, 2026-07-26) — shared → hosted: scoped auth
  (publish vs read tokens), a threaded cache server with first-writer-wins
  verdicts, key-addressed revocation, and the declared dependency set in the
  verification key; plus both contract generators (graphify import, the
  spec-kit extension) and strict provenance mode. (v0.4 was the rename
  release; Java, the fourth adapter, shipped in 0.3.2.)

What follows is where it goes next. The deferred-by-design items live in
[ISSUES.md](ISSUES.md) and the [issue tracker](https://github.com/davet47/hashloom/issues);
this is the prioritization.

## Theme for v0.5: shared → hosted

v0.2 made the cache shareable; v0.5 makes sharing it safe at team scale. The
remaining hard parts from [docs/hosted-store.md](docs/hosted-store.md):

- **Auth scoping** — ✓ **Shipped** (0.5.0): the cache server takes an
  optional `--publish-token`; reads accept either token (publish implies read),
  publishes require the publish token — CI writes greens, a laptop with the
  read token only consumes. A single token still grants both roles, so existing
  deployments are unchanged. Per-project/team tokens remain deferred.
- **Concurrent writers** — ✓ **Shipped** (0.5.0): the cache server is a
  `ThreadingHTTPServer` with a lock-serialised sqlite connection, and verdict
  publishes are first-writer-wins on the verification key — a duplicate
  publish is a no-op, never a `ran_at` refresh or `stale` reset. WAL +
  per-thread connections remain the documented throughput follow-up.
- **Cross-graph invalidation** — ✓ **Shipped** (0.5.0) as *key-addressed
  revocation*: analysis showed content-addressed keys already propagate
  contract changes across graphs (every dependent's key moves), so the
  graph-keyed shared `mark_stale` was deliberately not built. What shipped
  closes the real residual gap — greens that were wrong at publish time
  (flaky, env drift) used to be immortal team-wide; `POST /stale` tombstones
  their keys (with audit, restore, and name sweeps), and a revoked key stays
  stale under any publish. See docs/hosted-store.md item 5 for the full
  argument.
- **Dependency set in the key** — ✓ **Shipped** (0.5.0): the toolchain
  identity now carries a ` deps <file>=<sha256-12>` suffix over the project's
  committed dependency source (lockfile, or declared manifest as fallback),
  CRLF-normalised so cross-OS checkouts share. A green from a different
  declared dependency set is never trusted; projects with no dependency
  source keep the version-only identity, so nothing busts for them. OS/arch
  stays out deliberately — the CI(Linux)-serves-laptops promise holds, and
  installed-env drift remains revocation's job (see docs/hosted-store.md
  item 3 for the decisions).

## Sharpening the verification model (continuing)

- **Fixture coverage in the test-source hash** — #18 hashes each test
  function's own AST, not the conftest fixtures and helpers it calls; changing
  only those does not force a re-run yet. The README documents this caveat;
  closing it is the next precision/soundness item.
- **Facet-aware invalidation**
  ([#67](https://github.com/davet47/hashloom/issues/67)) —
  `put_contract`'s semantic diff already reports
  *which* facet of a contract changed (signature / deps / examples /
  invariants), but invalidation ignores that precision: any hash-relevant
  change marks every transitive dependent stale. The sharpening is letting a
  dependent declare — or hashloom infer — which facets it actually leans on, so
  an examples-only change doesn't re-verify a dependent that only consumes the
  signature. Pure precision work inside the existing model — no new surface
  (5 MCP tools, 5 CLI commands unchanged). Unscheduled: it queues behind
  fixture coverage (the #18 follow-up above) and the v0.5 hosted-store theme.
- **The deterministic-test caveat** — a cached green assumes deterministic
  tests, so a pass that depended on wall-clock time, network, or randomness can
  outlive the condition that made it pass. The README states the caveat
  honestly; shrinking it (flakiness detection, an optional re-verify TTL, or
  marking tests untrusted-for-caching) is open design work, not yet scheduled.
- **Strict provenance mode** ([#49](https://github.com/davet47/hashloom/issues/49))
  — ✓ **Shipped** (0.5.0): `.hashloom/config.json` `{"strict_provenance":
  true}` upgrades verify's inferred-contract warnings to structured refusals
  (`inferred_contract`); reads and writes stay advisory. Landed with no schema
  change, as designed.

## Bigger bets

- **Further languages** — the adapter seam is proven four deep (Python, Go,
  TypeScript, Java, chosen by impl extension) and is itself under contract
  (`contracts/LanguageAdapter.yaml`, the adapter specification: six methods,
  extension routing, hashing and error-shape invariants). Each additional
  language is real work — a normalised-AST hasher plus a test-runner
  integration — but now lands against a spec, not a convention.
- **Tessl spec-format compatibility** — an import/export adapter, once that
  format is stable.

## Pre-1.0 polish

- A single error-code naming convention (`bad_*` vs `invalid_*`).

## Explicitly not doing

No new contract syntax — contracts stay plain YAML. Guarding this is how the
project avoids "scope creep toward Loom." Keep the surface minimal: 5 MCP tools,
5 CLI commands.

## Suggested sequencing

1. **Hosted-store hardening** (the v0.5 theme): auth scoping, concurrent
   writers, cross-graph invalidation — then the dependency set in the key.
2. **Fixture coverage** in the test-source hash, and strict provenance mode
   (#49) if demand shows up.
3. **Tessl compatibility** and the error-code naming convention.
