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

## How to run

```bash
uv run pytest                       # full suite — hash stability is load-bearing
uv run python bench/benchmark.py    # the DoD number
```

CI (`.github/workflows/ci.yml`) runs both on every push and PR, so the DoD and
hash-stability rules are enforced, not just documented. Keep it green.

Python >=3.10. Deps: mcp, pyyaml, tiktoken, pytest.
