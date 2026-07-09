# ts-cart — the TypeScript example

8 contracts over a small shopping cart: SKU and line-item types, active-row
filters and counts, subtotals, discounts, and price formatting. The `.ts` impl extension routes every unit
through the TypeScript adapter — hashing via this project's *own* `typescript`
compiler API, verification via Node's built-in `node:test` (no runner
dependency at all).

Commands assume `heddle` is on PATH (`pip install heddle-mcp`). Working from
this repo's checkout instead, prefix every `heddle` command with `uv run`.

## Prerequisites

- Node >= 22.6 (`node` on PATH, or `.heddle/config.json` → `{"node": "..."}`)
- `npm install` **first**, from this directory — it provides the `typescript`
  package the hasher resolves; without a resolvable `typescript` (here or in
  an ancestor's `node_modules`) every unit errors with `bad_toolchain`

## Run the tests directly

```bash
node --test --experimental-strip-types 'cart/*.test.ts'
```

## The heddle loop

```bash
heddle init && heddle index       # derive the store from contracts/
heddle verify --radius Sku        # gate the widest blast radius in the project
heddle status                     # dirty units, cache hit-rate
```

The first `verify` runs `node:test` per unit; run it again and every unit
returns `cached-pass` without executing a single test. (A project that
declares `vitest` or `jest` in its package.json gets that runner instead —
auto-detected; this one deliberately has no runner dependency.)

## Watch a change find its blast radius

Edit the body of `discountCents` in [cart/pricing.ts](cart/pricing.ts), then:

```bash
heddle verify --radius discountCents
```

Exactly one unit re-runs: `totalCents` leans on `discountCents`'s *contract*,
which didn't change, so its cached green stands. Reformatting and comment
edits change no hash — the compiler API sees through them.

## Point an agent at it

```bash
heddle serve    # MCP over stdio: get_contract, put_contract, get_dependents, verify, status
```

The agent workflow and working rules live in
[docs/getting-started.md](../../docs/getting-started.md); the token accounting
for this project is in [docs/benchmarks.md](../../docs/benchmarks.md).
