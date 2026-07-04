# Roadmap

**Shipped so far** (full detail in the [CHANGELOG](CHANGELOG.md)):

- **v0.1** (0.1.0 → PyPI as `heddle-mcp`, 2026-06-23) — the engine:
  content-addressed contracts, a hash-keyed verification cache, and a
  blast-radius query, over MCP. Single-process and Python-only by design.
- **v0.2** (0.2.0 → PyPI, 2026-07-04) — solo → team: a shared verification
  cache (`LayeredStore` + `RemoteStore` + `python -m heddle.cache_server`) with
  the toolchain folded into the verification key so cross-machine greens are
  sound; **Go** and **TypeScript** adapters behind the per-extension adapter
  seam; semantic diff in `put_contract`; test source in the key (#18);
  invariants out of the hash (#19); the `rechecks`/`wasted_rate` block in
  `status` (#20); contract provenance (`status: inferred | confirmed`); and
  gate-shaped verify (a hard `ok` bit plus `--radius`, so one call gates a
  change's whole blast radius).

What follows is where it goes next. The deferred-by-design items live in
[ISSUES.md](ISSUES.md) and the [issue tracker](https://github.com/davet47/heddle/issues);
this is the prioritization.

## Theme for v0.3: shared → hosted

v0.2 made the cache shareable; v0.3 makes sharing it safe at team scale. The
remaining hard parts from [docs/hosted-store.md](docs/hosted-store.md):

- **Auth scoping** — split publish from read: CI can write greens, a laptop can
  only consume them. Today one bearer token does both.
- **Concurrent writers** — the cache server is single-threaded-serialised;
  real teams need atomic verdict/blob writes under concurrency (CAS or
  equivalent), not politeness.
- **Cross-graph invalidation** — a shared green is keyed by content hashes, but
  nothing yet propagates "this contract changed upstream" across clients whose
  local graphs disagree.
- **Dependency set in the key** — the deeper soundness knob: fold the lockfile /
  resolved dependency set (and possibly OS/arch) into the toolchain identity, so
  a green from an environment with different third-party versions is not
  trusted.

## Sharpening the verification model (continuing)

- **Fixture coverage in the test-source hash** — #18 hashes each test
  function's own AST, not the conftest fixtures and helpers it calls; changing
  only those does not force a re-run yet. The README documents this caveat;
  closing it is the next precision/soundness item.
- **The deterministic-test caveat** — a cached green assumes deterministic
  tests, so a pass that depended on wall-clock time, network, or randomness can
  outlive the condition that made it pass. The README states the caveat
  honestly; shrinking it (flakiness detection, an optional re-verify TTL, or
  marking tests untrusted-for-caching) is open design work, not yet scheduled.
- **Strict provenance mode** ([#49](https://github.com/davet47/heddle/issues/49))
  — an opt-in config that upgrades inferred-contract warnings to structured
  refusals, for teams that want unvetted contracts to hard-fail. Deferred by
  design; layerable with no schema change.

## Bigger bets

- **Further languages** — the adapter seam is proven three deep (Python, Go,
  TypeScript, chosen by impl extension). Each additional language is real work:
  a normalised-AST hasher plus a test-runner integration.
- **Tessl spec-format compatibility** — an import/export adapter, once that
  format is stable.

## Pre-1.0 polish

- A single error-code naming convention (`bad_*` vs `invalid_*`).

## Explicitly not doing

No new contract syntax — contracts stay plain YAML. Guarding this is how the
project avoids "scope creep toward Loom." Keep the surface minimal: 5 MCP tools,
5 CLI commands.

## Suggested sequencing

1. **Hosted-store hardening** (the v0.3 theme): auth scoping, concurrent
   writers, cross-graph invalidation — then the dependency set in the key.
2. **Fixture coverage** in the test-source hash, and strict provenance mode
   (#49) if demand shows up.
3. **Tessl compatibility** and the error-code naming convention.
