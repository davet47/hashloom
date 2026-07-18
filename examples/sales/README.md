# sales — the Python example

The flagship example: 20 contracts over a small sales-analytics library, with
a contract graph up to six deep (types → filters → metrics → segment reports).
This is the project behind the README's headline benchmark and the deepest
graph of the four examples, so blast-radius queries are at their most
interesting here.

Commands assume `hashloom` is on PATH (`pip install hashloom`). Working from
this repo's checkout instead, prefix every `hashloom` command with `uv run`.

## Prerequisites

- Python >= 3.10 with `pytest` (in this repo's checkout, `uv run` provides it)

## Run the tests directly

```bash
python -m pytest        # from this directory; `uv run pytest` in the checkout
```

## The hashloom loop

```bash
hashloom init && hashloom index     # derive the store from contracts/
hashloom verify --radius Sale     # gate a 16-unit blast radius (Region ties it)
hashloom status                   # dirty units, cache hit-rate, resolved interpreter
```

The first `verify` runs pytest per unit; run it again and every unit returns
`cached-pass` without executing a single test.

## Watch a change find its blast radius

Edit the body of `included_sales` in [src/filters.py](src/filters.py) — tweak
how incomplete sales are excluded, say — then:

```bash
hashloom verify --radius included_sales
```

Exactly one unit re-runs; its twelve dependents stay `cached-pass`, because
they lean on `included_sales`'s *contract*, which didn't change. Now edit a
contract instead — add a field to [contracts/Sale.yaml](contracts/Sale.yaml)'s
signature and `hashloom index` — and `verify --radius Sale` re-verifies
everything downstream of the type. Cosmetic edits (comments, formatting,
docstrings) change no hash and re-verify nothing.

## Bootstrap contracts from a graphify graph

This project's contracts are hand-written, but they didn't have to be: the
[graphify importer](../../integrations/graphify_import.py) can draft them from
a [graphify](https://github.com/Graphify-Labs/graphify) knowledge graph — the
brownfield entry point when code exists and contracts don't. The graph gives
structure (impl locations, dependencies, candidate tests); humans add
invariants and examples during review.

```bash
uv tool install graphifyy            # the `graphify` CLI
graphify extract . --code-only       # local tree-sitter, no API keys needed

# rank candidate seams by how many units depend on them
uv run python ../../integrations/graphify_import.py graphify-out/graph.json --root . --list

# draft contracts for the seams you pick — everything lands status: inferred
uv run python ../../integrations/graphify_import.py graphify-out/graph.json --root . \
    --units src/metrics.py::revenue_by_region src/types.py::Sale

hashloom index && hashloom status    # status shows the inferred review queue
```

Here the importer refuses to run as-is — these contracts already exist, which
is the point (`--force` overwrites, `--dry-run` inspects). To see the real
flow, copy this directory somewhere, delete its `contracts/`, and run the
commands above; then diff a drafted contract against the hand-written one.

## Point an agent at it

```bash
hashloom serve    # MCP over stdio: get_contract, put_contract, get_dependents, verify, status
```

The agent workflow and working rules live in
[docs/getting-started.md](../../docs/getting-started.md); the token accounting
for this project is in [docs/benchmarks.md](../../docs/benchmarks.md).
