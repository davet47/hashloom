## What and why

<!-- What does this change do, and why? Link any issue it closes. -->

## Checklist

- [ ] `uv run pytest` passes (full suite).
- [ ] Touches `contract.py` or `implhash.py`? The hash-stability tests
      (`tests/test_contract_hash.py`, `tests/test_implhash.py`) still pass, and
      any change to what busts a hash is intentional.
- [ ] Touches the context packets or hashing? `uv run python bench/benchmark.py`
      still reports >5x.
- [ ] Scope: this does not expand the 5-MCP-tool / 5-CLI-command surface, or it
      was discussed in an issue first.
- [ ] Tool errors stay structured (`HashloomError`); no stack traces over MCP.
