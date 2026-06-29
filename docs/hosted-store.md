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

## From MVP to hosted (the hard parts)

1. ✓ **Transport + backend (shipped).** `RemoteStore` (`remote.py`) implements the
   four team-portable methods (get/record a verdict, get/put a blob) against a
   server over a tiny JSON HTTP API; the server is `cache_server.py`, a stdlib
   `http.server` wrapping a `SqliteStore`, run as `python -m heddle.cache_server`.
   Selected via `.heddle/config.json` `{"shared": {"url","token"}}` and wrapped in
   at one `build_store()` factory, so the 5-tool / 5-CLI surface does not grow. A
   shared-store outage degrades silently to local verify (the local path stays the
   default). Single-threaded for now; concurrency stays in #4. Server-side `ran_at`
   stamping (the server's own `SqliteStore`) already covers #6.
2. **Auth** *(partially shipped)*. A single shared bearer token gates the server
   (constant-time `hmac.compare_digest`). Still deferred: a *stronger* check on the
   publish path than the read path, and per-project/team tokens.
3. **Trust model.** Who may publish a green? A shared stale-green is worse than a
   solo one, which is why test source is already in the verification key (#18):
   a verdict is only as portable as its key is complete. A hosted store should
   also pin the resolved toolchain in the key before trusting a cross-machine
   green. **This is the next slice:** until it lands, a hosted green is sound only
   across machines sharing the contract's toolchain (same Python/Go/Node + deps);
   the plan is a new `LanguageAdapter.toolchain_identity()` folded into
   `verification_key`.
4. **Concurrent writers.** The local `fcntl` lock (see `project.py`) becomes a
   server-side concern: transactional upserts and last-writer-wins or CAS on the
   verdict rows. (The current server is single-threaded, so writes already
   serialise; CAS is for a threaded/multi-process server.)
5. **Cross-graph invalidation.** When a shared contract changes, dependents'
   shared verdicts must be invalidated for the whole team, not just locally.
   `mark_stale` needs a shared analogue keyed off the dependency graph.
6. **Clocks.** `ran_at` is client-generated today; a shared store should stamp
   server-side to order writes without trusting client clocks.

## Running the cache server

The shared backend is an operational process, **not** a `heddle` subcommand (the
5-CLI surface is fixed):

```bash
python -m heddle.cache_server --db cache.db --token SECRET   # --host/--port optional
```

It refuses to start without a token (`--token` or `HEDDLE_CACHE_TOKEN`) and binds
`127.0.0.1` by default. Point each developer's `.heddle/config.json` at it:

```json
{ "shared": { "url": "http://cache.host:8770", "token": "SECRET" } }
```

Then `heddle verify` (and the MCP `verify` tool) publish greens to, and read them
from, the shared cache transparently — no surface change, and if the server is
down, verify just runs locally.

## Why this order

The MVP proves the seam and the payoff cheaply and is fully testable offline.
Each hard part above is independent and can land behind the same Protocol
without disturbing the local single-process path, which stays the default.
