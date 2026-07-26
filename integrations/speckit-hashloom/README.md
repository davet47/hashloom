# speckit-hashloom — the cache-and-gate loop for spec-kit

A [GitHub spec-kit](https://github.com/github/spec-kit) extension that wires
hashloom's contract verification into the spec-driven workflow. No hashing is
reimplemented anywhere — the scripts shell out to the `hashloom` CLI
(`index`, `verify --radius`, `status`), so the cache keeps its soundness
guarantees (normalised-AST hashing, test source and toolchain identity in the
verification key).

The loop:

```
/speckit.plan
      │
/speckit.hashloom.seams     draft seam contracts (status: inferred) into the
      │                     project's contracts/ + a per-feature seams.txt
/speckit.implement
      ├─ before_implement   precheck: verify the seams; tasks whose units are
      │                     already cached-pass get marked done, not redone
      ├─ ... tasks run ...
      └─ after_implement    gate: hashloom verify --radius over every seam
                            must return ok — the definition of done
```

## Install

In a spec-kit project (`specify init`), with hashloom on PATH:

```bash
pip install hashloom          # or: uv tool install hashloom
specify extension add /path/to/hashloom/integrations/speckit-hashloom --dev
```

## What it writes

- `contracts/*.yaml` at the **project root** — drafted seam contracts, always
  `status: inferred`; `hashloom status` lists them as your review queue.
- `FEATURE_DIR/seams.txt` — one contract name per line (`#` comments); the
  gate runs over exactly these names.

Nothing else. The store (`.hashloom/store.db`) is derived from `contracts/`
by `hashloom index`, as always.

## The gate script

`scripts/bash/hashloom-gate.sh <precheck|gate> FEATURE_DIR` prints one JSON
object: `ok`, `results.{cached_pass,pass,fail,error}`, `spec_only` (types
with no impl), `inferred` (review queue, when non-empty), `note` (when there
was nothing to gate). Exit codes: `0` ok or nothing-to-gate (precheck never
blocks), `1` gate red, `2` infrastructure (`hashloom_not_found`,
`index_failed`, `no_feature_dir`, `usage`).

CI backstop (the same gate as one plain command, no spec-kit needed):

```bash
hashloom verify --radius $(grep -v '^#' specs/NNN-feature/seams.txt)
```

## Caveats

- **Cache-skip is command-granular.** Spec-kit hooks fire per command, not
  per task, so the precheck maps cached-pass units onto tasks.md entries
  heuristically (unit name / file path match). Per-task keying would need
  core template overrides, which this extension deliberately avoids.
- **Bash-only scripts** in v1 (python3 is guaranteed wherever hashloom
  runs). No PowerShell twin yet; Windows users run the CI backstop line.
- **Spec-kit's extension API is pre-1.0** and moving. The manifest pins
  `speckit_version >=0.2.0`; expect churn. If `specify extension add`
  rejects the manifest, the fix is confined to `extension.yml` — the script
  and command prompts don't depend on the manifest schema. Last verified
  against specify-cli 0.14.3.dev0 (2026-07-26): install registers both
  hooks (`optional: false`) and, for Claude Code, exposes the commands as
  the `/speckit-hashloom-seams` and `/speckit-hashloom-gate` skills.
- **A red gate means not done**, regardless of what tasks.md says — the
  gate command instructs the agent accordingly, but hook execution is
  agent-mediated; the CI backstop above is the enforcement of record.
- For what a reviewed, gated contract graph looks like, see
  [`examples/sales`](../../examples/sales) in the hashloom repo.
