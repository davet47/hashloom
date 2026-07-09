# sales — the Python example

The flagship example: 20 contracts over a small sales-analytics library, with
a contract graph up to six deep (types → filters → metrics → segment reports).
This is the project behind the README's headline benchmark and the deepest
graph of the four examples, so blast-radius queries are at their most
interesting here.

Commands assume `heddle` is on PATH (`pip install heddle-mcp`). Working from
this repo's checkout instead, prefix every `heddle` command with `uv run`.

## Prerequisites

- Python >= 3.10 with `pytest` (in this repo's checkout, `uv run` provides it)

## Run the tests directly

```bash
python -m pytest        # from this directory; `uv run pytest` in the checkout
```

## The heddle loop

```bash
heddle init && heddle index     # derive the store from contracts/
heddle verify --radius Sale     # gate a 16-unit blast radius (Region ties it)
heddle status                   # dirty units, cache hit-rate, resolved interpreter
```

The first `verify` runs pytest per unit; run it again and every unit returns
`cached-pass` without executing a single test.

## Watch a change find its blast radius

Edit the body of `included_sales` in [src/filters.py](src/filters.py) — tweak
how incomplete sales are excluded, say — then:

```bash
heddle verify --radius included_sales
```

Exactly one unit re-runs; its twelve dependents stay `cached-pass`, because
they lean on `included_sales`'s *contract*, which didn't change. Now edit a
contract instead — add a field to [contracts/Sale.yaml](contracts/Sale.yaml)'s
signature and `heddle index` — and `verify --radius Sale` re-verifies
everything downstream of the type. Cosmetic edits (comments, formatting,
docstrings) change no hash and re-verify nothing.

## Point an agent at it

```bash
heddle serve    # MCP over stdio: get_contract, put_contract, get_dependents, verify, status
```

The agent workflow and working rules live in
[docs/getting-started.md](../../docs/getting-started.md); the token accounting
for this project is in [docs/benchmarks.md](../../docs/benchmarks.md).
