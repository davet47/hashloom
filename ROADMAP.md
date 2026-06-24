# Roadmap

**v0.1 shipped 0.1.0 to PyPI as `heddle-mcp` on 2026-06-23.** It is the engine:
content-addressed contracts, a hash-keyed verification cache, and a blast-radius
query, over MCP, single-process and Python-only by design. What follows is where
it goes next. The deferred-by-design items live in [ISSUES.md](ISSUES.md); this
is the prioritization.

## Theme for v0.2: solo → team

The single highest-leverage move, and the one the spec already named "the obvious
v0.2 candidate."

### The one big thing — hosted / team-shared store

Today the verification cache is a per-developer `.heddle/store.db`. Make it
shared: a teammate or CI verifies `revenue_by_region` green once, and everyone
else gets `cached-pass` for free. This is the leverage multiplier — and the
natural path to a hosted offering.

Scope: a store abstraction behind the current `Store`, a server backend, auth,
and sync/invalidation across concurrent writers. Biggest design lift in the
roadmap — worth its own design pass before any code.

### Supporting (ship alongside)

- **Semantic diff in `put_contract`** — report *what* changed in a contract, not
  just *that* it did and who it invalidated. High agent-UX value, moderate
  effort, no new store. Good first v0.2 motion.
- **Content-addressed implementation store** — store implementations by hash, not
  just their hashes. The natural enabler for a hosted store that can serve weft,
  not only verdicts.

### Sharpening the verification model

Direction toward a sharper verification model along two axes, soundness and
precision, so the README can eventually claim more than "caches verification
results." All three are filed as issues, not built:

- **Test source in the verification key** ([#18](https://github.com/davet47/heddle/issues/18)).
  Today the key is `(contract, impl, dep contract hashes)`, so a test-body edit
  alone does not force a re-run. Folding the resolved test source in is the
  precondition for any "caches correctness" language.
- **Invariants out of the binding hash** ([#19](https://github.com/davet47/heddle/issues/19)).
  Invariants are prose but currently sit inside the contract hash, so a reword
  cascades a re-verify across dependents. This is a precision fix, not a
  soundness one (it removes spurious re-verification, unlike #18 which closes a
  stale-green hole). Minimise the hashed prose surface.
- **Semantic necessity rate in `status`** ([#20](https://github.com/davet47/heddle/issues/20)).
  Count contract edits that busted the hash but changed zero verification
  outcomes, to measure how much re-verification is necessary versus cosmetic.

## v0.3+ — bigger bets

- **Multi-language** — a normalised-AST hasher + a test-runner adapter per
  language (Go and TypeScript first). The biggest expansion; each language is
  real work. The v0.1 interpreter-resolution and runner seams are the foundation.
- **Tessl spec-format compatibility** — an import/export adapter, once that format
  is stable.

## Pre-1.0 polish

The `launch-polish` pass (#17) shipped in 0.1.0: dropped the hard test count from
the README, added `heddle --version`, single-sourced the version via hatchling,
fixed the benchmark command to `uv run python`, added `src/heddle/py.typed`,
surfaced the resolved interpreter and the Repository/Issues URLs, and cleaned up
the packaging metadata.

Still open (post-launch):

- `CHANGELOG.md` and `CONTRIBUTING.md` + issue templates.
- A single error-code naming convention (`bad_*` vs `invalid_*`).

## Explicitly not doing

No new contract syntax — contracts stay plain YAML. Guarding this is how the
project avoids "scope creep toward Loom." Keep the surface minimal: 5 MCP tools,
5 CLI commands.

## Suggested sequencing

1. ✓ **v0.1 shipped** (0.1.0 on PyPI, demo gif live). Remaining: post the launch announcements ([docs/launch.md](docs/launch.md)).
2. **Semantic diff**: quick win, proves the v0.2 motion.
3. **Content-addressed impl store**: the enabler.
4. **Hosted store**: the big one (design pass first).
5. **Multi-language**: a v0.3 milestone of its own.
