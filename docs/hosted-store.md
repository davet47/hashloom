# Hosted / shared verification cache (design)

The v0.2 theme is solo to team: one teammate or CI verifies a unit green once,
and everyone else gets `cached-pass` for free. This is the design for that, plus
the thin MVP that ships now.

## The seam

`Store` is a Protocol (see `src/hashloom/store.py`), so the cache backend is
swappable. Two kinds of state are team-portable:

- **verification verdicts** (the `verifications` rows), and
- **impl-source blobs** (the content-addressed `blobs`), so the store can serve
  weft, not only verdicts.

Everything else (a developer's contracts, edges, impls, counters) stays local.

## What ships now: `LayeredStore` (MVP)

`src/hashloom/shared.py` fronts a local `Store` with a shared one:

- **read-through**: a local verdict miss consults the shared store; a green,
  non-stale row is back-filled locally and served. Blobs read local then shared.
- **write-through**: a green verdict and its blobs are written to both. Only
  greens are published (a failure is local and never crosses the boundary).

The shared store is just another `Store`, so today it is a second sqlite file.
Behind the Protocol it can later be a remote backend with no change to callers.
`tests/test_shared_store.py` shows client A's green served to client B without
B running pytest, and confirms failures are not published.

When the MVP first shipped it was not yet wired into the CLI/MCP and the
shared store was local-file only; both have since shipped — `build_store()`
wires the layered store into `index`/`status`/`verify` and the MCP server,
and `RemoteStore` makes the shared side an HTTP backend (item 1 below and
"Running the cache server").

## From MVP to hosted (the hard parts)

1. ✓ **Transport + backend (shipped).** `RemoteStore` (`remote.py`) implements the
   four team-portable methods (get/record a verdict, get/put a blob) against a
   server over a tiny JSON HTTP API; the server is `cache_server.py`, a stdlib
   `http.server` wrapping a `SqliteStore`, run as `python -m hashloom.cache_server`.
   Selected via `.hashloom/config.json` `{"shared": {"url","token"}}` and wrapped in
   at one `build_store()` factory, so the 5-tool / 5-CLI surface does not grow. A
   shared-store outage degrades silently to local verify (the local path stays the
   default). Single-threaded for now; concurrency stays in #4. Server-side `ran_at`
   stamping (the server's own `SqliteStore`) already covers #6.
2. **Auth** *(read/publish split shipped)*. Bearer tokens gate the server
   (constant-time `hmac.compare_digest`), and the roles are now split by verb:
   `--token` grants reads; an optional `--publish-token` is required for the
   publish routes (POST), and implies read. With only `--token`, that one token
   does both — the original deployment shape, unchanged. A read token on a
   publish route is 403 `read_only`; an unknown token is 401 `unauthorized`.
   Clients can also declare themselves read-only (`"publish": false` in the
   shared config) and skip publish requests entirely. Still deferred:
   per-project/team tokens.
3. ✓ **Trust: toolchain + dependency set in the key (shipped).** A shared
   stale-green is worse than a solo one, which is why test source is already in
   the verification key (#18): a verdict is only as portable as its key is
   complete. The key folds in a **toolchain identity**
   (`LanguageAdapter.toolchain_identity()`): the toolchain version (`python
   3.11.7` / `go 1.21.5` / `node <v> ts <v>` / `java 21.0.3`) plus, when the
   project commits a dependency source at its root, a
   `` deps <file>=<sha256-12>`` suffix over its CRLF-normalised bytes —
   `uv.lock` / `poetry.lock` / `Pipfile.lock` / `pdm.lock` /
   `requirements.txt` for Python, `go.sum` for Go, the npm/pnpm/yarn/bun
   locks for TypeScript, `gradle.lockfile` / `pom.xml` / `build.gradle(.kts)`
   for Java. A green from an environment with a different declared dependency
   set is not trusted; a project with no dependency source keeps the
   version-only identity, so nothing busts for it. Grain is the **committed
   declared set, never OS/arch** — a deliberate decision, recorded here where
   version-only was originally chosen: the lockfile is platform-invariant, so
   a CI(Linux) green still serves a dev on Mac/Windows whenever the checkout
   matches. Still not in the identity: OS/arch and installed-env drift
   (platform wheels, env markers, a venv that disagrees with its lockfile) —
   that residual class is what key-addressed revocation (#5) exists for.
   Known declared-grain leaks, filed in ISSUES: parent-pom/BOM and dynamic
   versions, `requirements.txt` `-r`/`-c` includes, `go.mod` local `replace`
   directives.
4. ✓ **Concurrent writers (shipped).** The server is a `ThreadingHTTPServer`;
   requests are handled concurrently while one lock serialises the single
   sqlite connection, so every db write stays an atomic single-statement
   commit. "CAS or equivalent" resolved as **first-writer-wins on verdict
   rows**: the verification key *is* the compare — one row per key, a
   duplicate publish (a re-run of a bit-identical closure) is a no-op that
   neither refreshes `ran_at` nor resets `stale`. That last part pre-closes
   the race with #5: a duplicate publish can never resurrect a row that
   cross-graph invalidation just marked stale. Unexpected handler errors
   return structured JSON 500s, never a stack trace. Deferred throughput
   path, if a team ever saturates the lock: WAL journal mode + per-thread
   connections + bounded busy-retry.
5. ✓ **Cross-graph invalidation (shipped as key-addressed revocation).** The
   literal design here used to read "`mark_stale` needs a shared analogue
   keyed off the dependency graph" — that mechanism was analyzed and
   deliberately **not built**, because content-addressed verification keys
   already are the cross-graph propagation: an upstream contract change moves
   every dependent's key, so new-graph clients never look up pre-change
   greens, and old-graph clients consuming old greens receive verdicts that
   are correct for their checkouts. A graph/name-keyed auto-mark would be
   harmful: the server holds no graph (contracts travel via git), name marks
   would strip old-graph clients of valid greens, a mid-edit `put_contract`
   on one laptop could tombstone the team's greens, and under first-writer-
   wins (#4) every mark is permanent. Do not re-implement the literal
   reading.

   What the key *cannot* see — and what shipped — is revocation of greens
   that were **wrong at publish time** at an unchanged key: flaky or
   nondeterministic passes, env drift outside the toolchain identity (dep
   set, OS), conftest/helper changes the test-source hash misses. Such a
   green used to be immortal team-wide. Now: `POST /stale`
   (publish-token-gated) tombstones verification keys — given directly, or
   as contract `names` the server resolves to their *existing* keys (a sweep
   marks what is, never future keys; dependent radii stay client-computed
   via `get_dependents` and passed as names). A revoked key stays stale
   under any publish (a `stale_marks` side table makes even
   mark-before-publish land stale); `{"stale": false}` is the only restore
   — and it takes **keys only**, so restoring a sweep can never lift
   tombstones the sweep did not create. Audit records are
   first-reason-wins: a later sweep never rewrites why a key was originally
   revoked. `GET /stale` lists every mark with its reason and timestamp.
   Remediation for clients that already back-filled a bad green:
   `rm .hashloom/store.db && hashloom index` — always safe, the *local*
   store is derived. The server's cache.db is not, which is why the restore
   route exists instead of "hand-edit sqlite". Automatic
   counter-evidence revocation (client fails where the cache is green) is
   deliberately deferred: toolchain identity is version-only, so one
   broken-env laptop could tombstone keys green for everyone else —
   revisit now that the declared dependency set is in the key (#3) — the
   false-contradiction class shrank to installed-env drift; see ISSUES.

   Revoking a green:

   ```bash
   # find the key: it's in verify_one's result, or GET /verification/<key>
   curl -X POST $BASE/stale -H "Authorization: Bearer $PUBLISH_TOKEN" \
        -d '{"keys": ["<64-hex>"], "reason": "flaky: needs local redis"}'
   curl $BASE/stale -H "Authorization: Bearer $READ_TOKEN"   # audit listing
   curl -X POST $BASE/stale -H "Authorization: Bearer $PUBLISH_TOKEN" \
        -d '{"keys": ["<64-hex>"], "stale": false}'          # undo
   ```
6. ✓ **Clocks (shipped for the shared path).** The cache server's own
   `SqliteStore` stamps `ran_at` server-side — the client's publish request
   carries no timestamp — so write ordering never trusts client clocks.
   Local stores still stamp locally, where ordering is single-writer anyway.

## Running the cache server

The shared backend is an operational process, **not** a `hashloom` subcommand (the
5-CLI surface is fixed):

```bash
python -m hashloom.cache_server --db cache.db --token READ_SECRET --publish-token CI_SECRET
```

It refuses to start without a token (`--token` or `HASHLOOM_CACHE_TOKEN`) and binds
`127.0.0.1` by default. `--publish-token` (or `HASHLOOM_CACHE_PUBLISH_TOKEN`) is
optional — omit it and the one token grants both roles. CI gets the publish token;
a developer laptop gets the read token and, optionally, opts out of doomed
publish attempts:

```json
{ "shared": { "url": "http://cache.host:8770", "token": "CI_SECRET" } }
```

```json
{ "shared": { "url": "http://cache.host:8770", "token": "READ_SECRET", "publish": false } }
```

Then `hashloom verify` (and the MCP `verify` tool) publish greens to, and read them
from, the shared cache transparently — no surface change, and if the server is
down, verify just runs locally.

## Why this order

The MVP proves the seam and the payoff cheaply and is fully testable offline.
Each hard part above is independent and can land behind the same Protocol
without disturbing the local single-process path, which stays the default.
