# Working rules for heddle

Heddle is a hash-keyed verification cache + content-addressed contract store,
exposed over MCP. Contracts are warp (durable), code is weft (regenerable). These
rules override default behavior — follow them.

## Git is the user's

**Commit and push only when the user explicitly asks** — never on your own, and
write **no `Co-Authored-By` trailer** when you do. The user owns the PR/merge flow
and brings local back to a clean, synced `main` before each new piece of work.

**A fresh branch per change.** The first action on any new feature/change is
`git switch -c <scoped-name>` off `main` — never commit to `main`, and never reuse
a previous feature branch for new work. One piece = one branch = one PR.

**Never git worktrees** — too much machinery for this project; the user dislikes
them. Don't reach for worktree isolation.

## Scope discipline

Anything not on the current milestone is an entry in [ISSUES.md](ISSUES.md) — file
it there, don't write the code. The named failure mode is "scope creep toward
Loom." Keep the surface minimal: **5 MCP tools, 5 CLI commands.** The README
documents "the entire surface"; if a change would add to it, stop and confirm.
(The shared-cache backend `python -m heddle.cache_server` is a deliberate
*operational* process, not a 6th CLI command — the client surface stays 5/5.)

## Heddle develops on heddle

The repo is itself a heddle project: `contracts/` holds contracts for the
stable seams (the five `api.py` functions, the `contract.py` hashing trio,
`impl_hash`, `verification_key`, `HeddleError`, the `Store` Protocol). The
workflow from [docs/getting-started.md](docs/getting-started.md) applies here:

- **Before changing a contracted seam**, check the blast radius (the
  `get_dependents` MCP tool when connected — it is not a CLI command);
  **after touching one**, `uv run heddle verify --radius <name>` must return
  `ok: true` — that is the inner-loop gate.
- **A new stable seam gets a contract before its implementation.** If you (the
  agent) derived the contract rather than the user specifying it, mark it
  `status: inferred`; the user flips it to `confirmed` on review. `heddle
  status` lists the review queue.
- **Do not contract churning interiors.** `remote.py`, `cache_server.py`, and
  `shared.py` are deliberately uncontracted while the v0.3 hosted-store work
  reshapes them; helpers (`tokens.py`, `project.py`) are weft. Pinning
  interiors is the failure mode the README warns about.
- **The heddle gate layers on the DoD — it never replaces it.** Full
  `uv run pytest` and the benchmark below remain the definition of done;
  heddle's cached verify must not be the only thing vouching for heddle.

## Definition of done: >5x token reduction

`bench/benchmark.py` is the DoD guard — it exits nonzero below 5x (currently
5x+). Run it for anything that could touch the context packets or hashing.
**Never regress it.**

## Hash stability is load-bearing

`tests/test_contract_hash.py` and `tests/test_implhash.py` are the spec. Cosmetic
input changes — whitespace, key order, comments, docstrings, file relocation —
must never change a hash; meaning changes (signature, invariant/example order)
must. If you touch `contract.py` or `implhash.py`, these tests are the contract.
Run `uv run pytest` (full suite) before declaring anything done.

## The store is derived

`.heddle/store.db` is rebuildable from `contracts/` via `heddle index` — never
hand-edit it. `contracts/*.yaml` is the source of truth.

## Errors are structured

Nothing leaks a stack trace over MCP. `_respond` in
[server.py](src/heddle/server.py) wraps every tool; raise `HeddleError(code,
message)` for anything an agent should see. Keep it that way.

## The verify interpreter

`verify` shells pytest out to a resolved interpreter (see
[config.py](src/heddle/config.py)), in precedence order:

1. `heddle serve --python PATH`
2. `.heddle/config.json` → `{"python": "..."}`
3. auto-detected project venv (`<root>/.venv/bin/python`, …)
4. `sys.executable`

So heddle can verify a target project against *its own* venv without being
installed into it. `heddle status` reports the resolved interpreter.

Non-Python impls resolve their own toolchain by the same precedence, keyed by the
impl extension: a `.go` impl uses `go` (`.heddle/config.json` → `"go"`); a
`.ts`/`.tsx` impl uses `node` (→ `"node"`) plus the project's *own* `typescript`,
and auto-detects the test runner (vitest / jest, else Node's `node:test`); a
`.java` impl uses `java` (→ `"java"`, JDK >= 11) and auto-detects the runner from
the build manifest (`pom.xml` → Maven, `build.gradle` → Gradle, committed
`mvnw`/`gradlew` wrappers preferred).

## How to run

```bash
uv run pytest                       # full suite — hash stability is load-bearing
uv run python bench/benchmark.py    # the DoD number
```

CI (`.github/workflows/ci.yml`) runs both on every push and PR, so the DoD and
hash-stability rules are enforced, not just documented. Keep it green.

Python >=3.10. Deps: mcp, pyyaml, tiktoken, pytest. TypeScript contracts also
need Node >=22.6 and the project's own `typescript` (CI installs a repo-local one
via `npm ci`; `node_modules/` is gitignored). Java contracts need a JDK >=11 plus
Maven or Gradle (CI installs Temurin; Maven ships on the runner).
