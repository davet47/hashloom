---
description: "Verify the feature's seams through the hashloom cache: cached-green precheck before implementation, hard verify --radius gate after"
---

# Hashloom Seam Gate

Runs the feature's seams through hashloom's cached verification. Invoked as
a hook by `/speckit.implement` (both `before_implement` and
`after_implement`), or directly by the user.

## User Input

$ARGUMENTS

## Determine the mode

- Invoked as a `before_implement` hook → mode `precheck`.
- Invoked as an `after_implement` hook → mode `gate`.
- Invoked directly: use `$ARGUMENTS` if it says `precheck` or `gate`;
  default to `gate`.

## Run the script

1. Run `.specify/scripts/bash/check-prerequisites.sh --json` from the repo
   root and parse `FEATURE_DIR` (absolute path).
2. From the repo root, run:

   ```bash
   .specify/extensions/hashloom/scripts/bash/hashloom-gate.sh <mode> <FEATURE_DIR>
   ```

3. Parse the single JSON object it prints:

   - `ok` — the verdict (`true`/`false`)
   - `results.cached_pass` — units proven green by the cache, no test ran
   - `results.pass` — units verified green just now
   - `results.fail` — `{name, summary}` for failing units
   - `results.error` — `{name, code, message}`: unknown contract names,
     missing impl files (not yet implemented), impls without tests, ...
   - `spec_only` — manifest names with no impl (types); nothing to run
   - `inferred` — contracts still awaiting human review (advisory)
   - `note` — present when there was nothing to gate (no/empty manifest)

Exit codes: `0` ok (including nothing-to-gate), `1` verification failed
(gate mode only), `2` infrastructure error (hashloom missing, index failed,
bad arguments — the JSON `error.code` says which).

## Mode: precheck (before_implement)

The precheck NEVER blocks implementation; it harvests cache hits.

1. If `note` is present (no seams), say so in one line and continue with
   implementation normally.
2. For every unit in `results.cached_pass`: find the task(s) in
   `FEATURE_DIR/tasks.md` whose whole purpose is implementing or testing
   that unit (match on the unit name or its impl/test paths in the task
   description). Mark each such task `[X]` and append
   `(cached-pass via hashloom — already verified)`. If a task covers more
   than the cached unit, leave it open and note the partial coverage.
3. Report a compact table: cached-pass (skipped work), pass, fail, error,
   spec_only. Units in `fail`/`error` are simply work the coming tasks must
   do — do not treat them as blockers here. Typically, not-yet-implemented
   units appear as errors (missing impl file); that is expected before
   implementation.
4. If the script exited `2`, report the `error.code`/`message` as a
   warning, tell the user the cache precheck was skipped, and continue.
5. Then proceed with implementation. While implementing, prefer the
   contract as the spec for each seam, and after finishing a unit run
   `hashloom verify --radius <name>` — green early beats red late.

## Mode: gate (after_implement)

The gate is the definition of done. It re-indexes (picking up any contract
edits made during implementation) and runs
`hashloom verify --radius` over every seam in the manifest — each unit plus
its full blast radius, cached greens served where nothing was invalidated.

1. Exit `0` and `ok: true` → the gate is green. Report the table
   (cached_pass / pass counts prove the cache did its job). If `inferred`
   is non-empty, remind the user: *these contracts are still machine-drafted
   — review them (`hashloom status` lists the queue) and flip to
   `confirmed`; the flip is free.*
2. Exit `1` → the gate is RED and implementation is NOT complete, no matter
   what tasks.md says. Do not report success; do not mark the feature done.
   For each entry in `results.fail` and `results.error`, show name +
   summary/message, then fix: re-read the contract
   (`contracts/<name>.yaml`) as the spec, repair the implementation or
   tests, and re-run this gate until green. If a *contract* itself proved
   wrong, say so explicitly and let the user decide the contract change —
   contracts are the user's to own.
3. Exit `2` → infrastructure problem (see `error.code`). Report it verbatim
   and treat the gate as NOT passed — an unprovable feature is not a done
   feature. Common causes: `hashloom_not_found` (install hashloom),
   `index_failed` (broken contract YAML — fix it), `no_feature_dir`.
