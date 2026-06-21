# Filed issues (v0.1 non-goals and follow-ups)

Per the v0.1 spec: if a task isn't on a milestone, it's an issue. These move to
the GitHub tracker once the repo has a remote.

## Deferred by design (spec non-goals)

1. **Multi-language support** — v0.1 is Python-only (AST hashing and pytest runner are Python-specific). Each language needs a normalised-AST hasher and a test-runner adapter.
2. **Content-addressed implementation store** — implementations remain plain files on disk; only their hashes live in the store.
3. **Hosted / team-shared store** — single-process, single sqlite file for now. A shared verification cache across a team is the obvious v0.2 candidate.
4. **Semantic diff rendering** — `put_contract` reports *that* a contract changed and who is invalidated, not a pretty diff of *what* changed.
5. **Tessl spec-format compatibility** — import/export adapter for Tessl-style spec files. Format is frozen for v0.1 as specced.
6. **New syntax of any kind** — contracts stay plain YAML.

## Known limitations / follow-ups

7. **PyPI release** — `pip install heddle` in the README assumes publication; cut 0.1.0 to PyPI.
8. **README gif** — record the Claude Code → heddle demo loop.
9. **Pre-existing stale bytecode** — the verification runner passes `-B` / `PYTHONDONTWRITEBYTECODE` so its own runs never cache bytecode, but a stale user-written `__pycache__` (same size, same mtime second) could still be loaded. Consider a `--no-pycache-trust` mode that clears `__pycache__` in the dep closure before running.
10. **Contract names are global** — no namespacing/packages; collisions across folders are unhandled (one `contracts/` dir per project for now).
11. **Name finalization** — "heddle" is a working name; rename is a find-and-replace.
