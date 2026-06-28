# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Semantic diff in `put_contract`: the response carries a `diff` of what changed
  versus the prior contract (signature, deps, invariants, examples, impl/tests).
- Test source in the verification key (#18): editing a test's body now forces a
  re-run; reformatting, comments, and docstrings in a test stay cached. Conftest
  fixtures and helpers a test calls are not yet covered.
- Content-addressed impl-source store: `heddle index` stores each impl file's
  source as a deduped blob, so the store can serve weft, not only verdicts.
- A backend-agnostic `Store` interface (a Protocol) with `SqliteStore` as the
  local implementation: the seam for a shared/remote cache.
- Shared verification cache MVP (`LayeredStore`): a local store fronted by a
  shared one (read-through, write-through for greens), so one client's verified
  green serves another. Design for the hosted service in docs/hosted-store.md.
- Multi-language adapters: contracts whose `impl` is a `.go` file verify with a
  Go adapter (a stdlib `go/ast` hash helper plus `go test -json`), chosen by the
  impl's extension. Python is unchanged and the default; the contract syntax and
  the 5-tool / 5-CLI surface are unchanged.

## [0.1.0] - 2026-06-23

First public release, published to PyPI as `heddle-mcp` (the import name and CLI
stay `heddle`).

### Added
- Content-addressed contracts: one hashable YAML file per software unit
  (signature, invariants, examples, dependencies), with subdirectory namespaces.
- Hash-keyed verification cache: a green test result keyed on the contract,
  implementation, and transitive dependency hashes. pytest runs only on a miss;
  failures are never served from cache.
- Mechanical blast radius: `get_dependents` reports the exact set of invalidated
  dependents, direct or transitive, by hash.
- Five MCP tools (`get_contract`, `put_contract`, `get_dependents`, `verify`,
  `status`) and five CLI commands (`init`, `index`, `serve`, `status`, `verify`).
- Configurable verify interpreter and timeout via `heddle serve --python`,
  `.heddle/config.json`, or an auto-detected project `.venv`.
- `--no-pycache-trust` / `pycache_trust` to clear stale `__pycache__` before a
  verify run.
- Structured errors over MCP (no stack traces).
- CI (tests on Python 3.10 through 3.13 plus the >5x benchmark guard) and PyPI
  Trusted Publishing on version tags.

[Unreleased]: https://github.com/davet47/heddle/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/davet47/heddle/releases/tag/v0.1.0
