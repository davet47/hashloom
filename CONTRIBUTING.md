# Contributing to heddle

Thanks for your interest. heddle is a hash-keyed verification cache and a
content-addressed contract store, exposed over MCP. Contracts are the durable
warp; code is the regenerable weft. A few rules keep it that way.

## Scope: the surface is fixed on purpose

heddle is deliberately small: **5 MCP tools and 5 CLI commands**, and the README
documents the entire surface. The named failure mode is "scope creep toward
Loom." Bug fixes and docs are welcome any time. A change that would add to that
surface needs a conversation first, so please open an issue before writing it.

## Development

Requires Python >= 3.10 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest                       # full suite
uv run python bench/benchmark.py    # the definition-of-done number
```

## Two things are load-bearing

1. **Hash stability.** `tests/test_contract_hash.py` and `tests/test_implhash.py`
   are the spec. Cosmetic input changes (whitespace, key order, comments,
   docstrings, file relocation) must never change a hash; meaning changes
   (signature, invariant or example order) must. If you touch `contract.py` or
   `implhash.py`, those tests are the contract.
2. **The >5x token reduction.** `bench/benchmark.py` is the definition-of-done
   guard and exits nonzero below 5x. Run it for anything that could touch the
   context packets or hashing, and never regress it.

Two more invariants worth knowing: nothing leaks a stack trace over MCP (tool
errors are structured `HeddleError(code, message)` values, see `server.py`), and
`.heddle/store.db` is derived state rebuildable from `contracts/` via `heddle
index`, so never hand-edit it. `contracts/*.yaml` is the source of truth.

## Pull requests

- Branch off `main`, one focused change per branch.
- `main` is protected: every PR must pass CI (pytest on Python 3.10 through 3.13,
  plus the benchmark guard) before it can merge. Run both locally first.
- Keep the diff scoped to one thing. If you spot an unrelated issue, file it.
- Match the surrounding code: its naming, comment density, and idioms.

Where the project is headed lives in [ROADMAP.md](ROADMAP.md); deferred non-goals
are in [ISSUES.md](ISSUES.md).

## Releases

Maintainer-only, via PyPI Trusted Publishing on a version tag. See
[RELEASING.md](RELEASING.md).
