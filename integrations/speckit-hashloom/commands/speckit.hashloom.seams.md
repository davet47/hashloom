---
description: "Draft hashloom contracts (status: inferred) for the feature's stable seams and register them for gating"
---

# Draft Feature Seams as Hashloom Contracts

Turn the current feature's *stable seams* — the interfaces other units will
depend on — into hashloom contracts, so `/speckit.implement` can serve cached
verification greens for anything already proven and hard-gate everything else.

Run this after `/speckit.plan` and ideally before `/speckit.tasks`, so task
descriptions can name the seams they implement.

## User Input

$ARGUMENTS

Optional: an explicit list of unit names to contract (overrides step 3's
selection), or `--skip` to record that this feature has no seams.

## Steps

### 1. Resolve context

- Run `.specify/scripts/bash/check-prerequisites.sh --json` from the repo root
  and parse `FEATURE_DIR`. All paths below are absolute.
- Read `FEATURE_DIR/plan.md` (and `data-model.md`, `contracts/`, `spec.md`
  where they exist) to understand the planned units.

### 2. Ensure a hashloom project exists

Run `hashloom status` from the repo root.

- If it succeeds, note the JSON: `dirty` (units without a current green) and
  `inferred` (contracts still awaiting human review) matter later.
- If it fails because there is no project (no `.hashloom/` marker), run
  `hashloom init` — it scaffolds `.hashloom/` and `contracts/` and touches
  nothing else. Tell the user you initialised it.

### 3. Choose the seams — stable seams only

Contracts are warp; code is weft. A contract belongs on a seam only when BOTH:

- **other units depend on it** — it is an interface, a shared type, a
  boundary function; and
- **you expect the interface to outlive its current implementation.**

Do NOT contract:

- private helpers or interiors you would happily rewrite — pinning them is
  the failure mode, not thoroughness;
- one-off glue with a single caller;
- anything this feature only *calls* but does not define or change (existing
  contracts already cover those seams — verify picks them up via deps).

A feature with only two or three trivial units needs no contracts at all:
write an empty manifest (step 6) with a comment saying so, report that to the
user, and stop. Dropping hashloom where it earns no place is correct use.

Typical yield for a mid-sized feature: 3–10 contracts.

### 4. Draft one contract per seam

Hashloom contracts are plain YAML with a closed schema — **unknown keys are
hard errors**. Allowed keys: `name`, `signature` (both required), `deps`,
`invariants`, `examples`, `tests`, `impl`, `status`.

```yaml
name: allow                      # maps to contracts/allow.yaml; '/' creates
                                 # namespace subdirs (billing/invoice)
signature: "(bucket: Bucket, now: float) -> bool"
deps: [Bucket, refill]           # other CONTRACT names this unit leans on —
                                 # existing contracts or ones in this batch
invariants:
  - never lets the bucket go below zero tokens
examples:
  - in: "bucket with 1 token"
    out: "True, and the token is spent"
tests: [tests/test_limiter.py::test_allow_spends_tokens]
impl: src/limiter.py::allow      # must contain '::'
status: inferred                 # ALWAYS — you drafted this, the human vets it
```

Rules:

- `status: inferred` on every contract you draft. It marks the spec as your
  guess at the user's intent; the human flips it to `confirmed` on review.
- An `impl`-bearing contract MUST list `tests` — an impl without tests fails
  verify by design (`no_tests`). Write the test node IDs now, with the
  contract, even though the files don't exist yet; the tasks phase will
  create them. Pytest node-id form: `path/to/test_file.py::test_name` (or
  `::TestClass::test_name`).
- Pure types (dataclasses, records) may be spec-only: `name` + `signature`
  (+ `invariants`), no `impl`/`tests`. They still anchor deps.
- `deps` are contract-graph edges, not imports: list only other contracted
  seams. A dep on a contract that will never exist fails `hashloom index`.
- Signatures use the language's natural form; for types use
  `"dataclass: Sale(region: str, amount: float)"` style.

### 5. Write the contracts — never overwrite silently

Contracts live in the PROJECT ROOT `contracts/` directory (hashloom's store
is derived from it) — NOT in `FEATURE_DIR/contracts/`.

For each drafted contract:

- If `contracts/<name>.yaml` does not exist, write it.
- If it exists and this feature intentionally CHANGES that seam, EDIT the
  existing file (keep its `status` unless the meaning changed; a meaning
  change on a confirmed contract should flip it back to `inferred` and be
  called out to the user — hashloom will re-verify every dependent).
- If it exists and the collision is accidental, pick a namespaced name
  (`<feature>/<name>`) or rename your unit. Never clobber.

### 6. Write the seams manifest

Write `FEATURE_DIR/seams.txt` — one contract name per line; `#` starts a
comment; blank lines ignored. List EVERY contract this feature defines or
edits, spec-only types included:

```text
# hashloom seams for 003-rate-limiter (gated by /speckit.hashloom.gate)
Bucket
refill
allow
```

This file is what the implement-phase hooks gate on.

### 7. Index and surface the review queue

```bash
hashloom index
```

Must succeed. On error (invalid contract, unknown dep) fix the YAML and
re-run — never leave the index red. Report the JSON
(`indexed` / `changed` / `removed` / `invalidated`).

Then:

```bash
hashloom status
```

Show the user the `inferred` list verbatim. Tell them: *these are drafted
specs, not vetted ones — your review queue. Review each like an interface:
is the signature right, are the invariants what you meant? Fix what's wrong;
for what's right, change `status: inferred` to `confirmed` (or delete the
line) and run `hashloom index`. The flip is free — nothing re-verifies.*

### 8. Report

Output a summary table: contract name, spec-only or impl-bearing, deps,
new/edited, and the manifest path. Remind the user that
`/speckit.implement` will now precheck these seams against the cache and
hard-gate on `hashloom verify --radius` at the end.
