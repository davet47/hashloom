# go-ledger — the Go example

8 contracts over a small double-entry ledger: entry and account types, debit /
credit totals, a balance check, per-account balances, and dollar formatting. The `.go` impl
extension routes every unit through the Go adapter — hashing via the stdlib
`go/ast`, verification via `go test`.

Commands assume `hashloom` is on PATH (`pip install hashloom`). Working from
this repo's checkout instead, prefix every `hashloom` command with `uv run`.

## Prerequisites

- a Go toolchain (`go` on PATH, or `.hashloom/config.json` → `{"go": "..."}`)

## Run the tests directly

```bash
go test ./...
```

## The hashloom loop

```bash
hashloom init && hashloom index     # derive the store from contracts/
hashloom verify --radius Account  # gate the widest blast radius: 7 of the 8 units
hashloom status                   # dirty units, cache hit-rate
```

The first `verify` runs `go test -json` per unit; run it again and every unit
returns `cached-pass` without executing a single test.

## Watch a change find its blast radius

Edit the body of `TotalDebits` in [ledger/totals.go](ledger/totals.go), then:

```bash
hashloom verify --radius TotalDebits
```

Exactly one unit re-runs: `Balanced` leans on `TotalDebits`'s *contract*,
which didn't change, so its cached green stands. Reformatting,
comments, and doc-comment edits change no hash at all — `go/ast` sees through
them.

## Point an agent at it

```bash
hashloom serve    # MCP over stdio: get_contract, put_contract, get_dependents, verify, status
```

The agent workflow and working rules live in
[docs/getting-started.md](../../docs/getting-started.md); the token accounting
for this project is in [docs/benchmarks.md](../../docs/benchmarks.md).
