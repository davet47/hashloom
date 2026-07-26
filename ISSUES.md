# Filed issues (v0.1 non-goals and follow-ups)

Per the v0.1 spec: if a task isn't on a milestone, it's an issue. The repo now
has a remote, so new follow-ups are filed on the GitHub tracker (the
verification-model sharpening lives there as
[#18](https://github.com/davet47/hashloom/issues/18) through
[#20](https://github.com/davet47/hashloom/issues/20), prioritised in
[ROADMAP.md](ROADMAP.md)). This file keeps the original spec non-goals and the
launch follow-ups, with status as of the 0.1.0 release (shipped 2026-06-23).

## Deferred by design (spec non-goals)

1. **Multi-language support**: v0.1 is Python-only (AST hashing and pytest runner are Python-specific). Each language needs a normalised-AST hasher and a test-runner adapter. (Go and TypeScript shipped post-0.1.0, chosen by impl extension; see ROADMAP.)
2. **Content-addressed implementation store**: implementations remain plain files on disk; only their hashes live in the store. (v0.2 enabler, see ROADMAP.)
3. **Hosted / team-shared store**: single-process, single sqlite file for now. The shared verification cache is the v0.2 theme (see ROADMAP).
4. **Semantic diff rendering**: `put_contract` reports *that* a contract changed and who is invalidated, not a pretty diff of *what* changed. (Queued for v0.2.)
5. **Tessl spec-format compatibility**: import/export adapter for Tessl-style spec files. Format is frozen for v0.1 as specced.
6. **New syntax of any kind**: contracts stay plain YAML.

## Known limitations / follow-ups

7. **PyPI release**: ✓ **Resolved in 0.1.0.** Published as `heddle-mcp` (the bare `heddle` name was held by a third-party placeholder) via GitHub Actions Trusted Publishing; the import name and CLI stayed `heddle` through 0.3.3. Since the 0.4.0 rename the distribution, import name, and CLI are all `hashloom` — see item 10. See [RELEASING.md](RELEASING.md).
8. **README gif**: ✓ **Resolved in 0.1.0.** Recorded and embedded under the CI badge; storyboard in [docs/demo.md](docs/demo.md).
9. **Pre-existing stale bytecode**: partially mitigated. The verification runner passes `-B` / `PYTHONDONTWRITEBYTECODE` so its own runs never cache bytecode, but with the default `pycache_trust: true` a stale user-written `__pycache__` (same size, same mtime second) could still be loaded. Mitigation shipped: set `pycache_trust: false` (or `--no-pycache-trust`) to clear `__pycache__` before each verify run. Making that the default remains a possible future change.
10. **Name finalization**: ✓ **Resolved**, then revised. "heddle" was the locked project name through 0.3.3 (PyPI: `heddle-mcp`); renamed to **hashloom** in 0.4.0 after two unrelated "heddle" MCP servers surfaced — see the CHANGELOG's 0.4.0 entry. The bare `hashloom` PyPI name is ours.
11. **Demo gif**: ✓ **Resolved in 0.1.0** (same work as #8): the Claude Code to heddle loop is recorded and embedded.
12. **Contract names are global**: ✓ **Resolved.** Subdirectory namespaces shipped, so the same short name can live in different folders (`contracts/billing/invoice.yaml` is the contract `billing/invoice`). One `contracts/` directory per project still holds.
13. **TypeScript runner — live vitest/jest coverage**: the TS adapter auto-detects vitest / jest / `node:test` from `package.json`. `node:test` (the zero-dependency default) is exercised end-to-end in `tests/test_typescript_adapter.py`; the vitest/jest backends (a shared jest-shaped JSON report) are implemented and the detection logic is unit-tested, but a live vitest/jest run is not yet in heddle's own suite. Follow-up: add a hermetic vitest fixture and validate the JSON parser against a real run.
14. **TypeScript `node:test` strip-types limits**: under `node:test`, `.ts` runs via Node's native type-stripping (Node >=22.6), which can't erase type-only constructs that need code generation (`enum`, namespaces, parameter properties) without `--experimental-transform-types`; such a test file surfaces as `tests_failed_to_run`. Projects using those should declare vitest or jest (which transpile fully) — the adapter will auto-detect and use them.
15. **Pull-without-reindex freshness gap**: `verify` computes keys from `store.db`'s contract hashes, so a `git pull` without `hashloom index` can serve a cached-pass that no longer matches the contracts on disk. Identical with or without a shared store (the key is computed client-side). Candidate fix: a verify-time freshness check against `contracts/` on disk. Surfaced during the cross-graph-invalidation analysis.
16. **Post-revert spurious re-run**: the local name-keyed stale row survives a `git revert`, shadowing a still-valid shared green at the old key and forcing one wasted pytest run. Sound (never a wrong serve), just a perf papercut. Candidate fix: a guarded fall-through in `LayeredStore.get_verification` when the local row is stale but the shared row at the same key is green — sound only under the invariant that local staleness is content-triggered, so it needs its own reviewed change.
17. **Automatic counter-evidence revocation**: when a client's real run fails at a key where the shared cache holds a green, that contradiction is the flaky-test signature and could auto-fire `POST /stale`. Deferred deliberately: toolchain identity is version-only, so one broken-env laptop computes the same key and would tombstone keys green for everyone else — permanently under first-writer-wins, re-firing on every verify (a treadmill even against the restore route). Revisit after the dependency set enters the verification key.
18. **Verdict-row retention**: old-key verification rows are never deleted, locally or (now) server-side, and `status`'s `stale_verifications` lists a name forever after a change even once its current key is green. Rows are tiny and content-addressed, so this is bounded-growth housekeeping, not soundness — but retention/GC should be a conscious decision. Also filed here: the optional `shared_stale_refused` observability counter skipped in the revocation PR to keep the client diff at zero.
19. **`RemoteStore.get_blob` trusts the server**: the returned content is never re-hashed against the requested hash. One-line hardening (`hashlib.sha256(content).hexdigest() == blob_hash` or return None) that keeps a compromised/buggy shared cache from serving wrong weft.
