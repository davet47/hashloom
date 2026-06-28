# Hosted / shared verification cache (design)

The v0.2 theme is solo to team: one teammate or CI verifies a unit green once,
and everyone else gets `cached-pass` for free. This is the design for that, plus
the thin MVP that ships now.

## The seam

`Store` is a Protocol (see `src/heddle/store.py`), so the cache backend is
swappable. Two kinds of state are team-portable:

- **verification verdicts** (the `verifications` rows), and
- **impl-source blobs** (the content-addressed `blobs`), so the store can serve
  weft, not only verdicts.

Everything else (a developer's contracts, edges, impls, counters) stays local.

## What ships now: `LayeredStore` (MVP)

`src/heddle/shared.py` fronts a local `Store` with a shared one:

- **read-through**: a local verdict miss consults the shared store; a green,
  non-stale row is back-filled locally and served. Blobs read local then shared.
- **write-through**: a green verdict and its blobs are written to both. Only
  greens are published (a failure is local and never crosses the boundary).

The shared store is just another `Store`, so today it is a second sqlite file.
Behind the Protocol it can later be a remote backend with no change to callers.
`tests/test_shared_store.py` shows client A's green served to client B without
B running pytest, and confirms failures are not published.

What the MVP does NOT do yet: it is not wired into the CLI/MCP (no surface
change), and the shared store is local-file only. Wiring is below.

## From MVP to hosted (the hard parts, deferred)

1. **Transport + backend.** Implement `Store` against a server (HTTP/gRPC).
   The verdict/blob methods are the only ones that must be remote; the rest can
   stay local. Selected via `.heddle/config.json` (`{"shared": {...}}`), so the
   5-tool / 5-CLI surface does not grow.
2. **Auth.** A token per project/team. The publish path (record a green) needs a
   stronger check than the read path.
3. **Trust model.** Who may publish a green? A shared stale-green is worse than a
   solo one, which is why test source is already in the verification key (#18):
   a verdict is only as portable as its key is complete. A hosted store should
   also pin the resolved toolchain in the key before trusting a cross-machine
   green.
4. **Concurrent writers.** The local `fcntl` lock (see `project.py`) becomes a
   server-side concern: transactional upserts and last-writer-wins or CAS on the
   verdict rows.
5. **Cross-graph invalidation.** When a shared contract changes, dependents'
   shared verdicts must be invalidated for the whole team, not just locally.
   `mark_stale` needs a shared analogue keyed off the dependency graph.
6. **Clocks.** `ran_at` is client-generated today; a shared store should stamp
   server-side to order writes without trusting client clocks.

## Why this order

The MVP proves the seam and the payoff cheaply and is fully testable offline.
Each hard part above is independent and can land behind the same Protocol
without disturbing the local single-process path, which stays the default.
