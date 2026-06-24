# Demo gif storyboard (ISSUES #8)

The launch gif shows the Claude Code → heddle regeneration loop: an agent
re-weaves one unit cheaply, with heddle serving the ~300-token spec packet and a
cached verification instead of raw files. Drop the finished gif at the top of the
README, under the CI badge.

**Target:** ~25–35 s, silent with captions, looping. Terminal ~100×30, large
font. Record with any screen recorder → `gifski` or `ffmpeg` for the gif.

## Setup (off-camera)

```bash
# the number (scene 2) runs from the repo root:
uv run python bench/benchmark.py        # rehearse once; it's deterministic

# the loop (scenes 3–8) runs in the sample project:
cd examples/sales
rm -rf .heddle && heddle init && heddle index
```

## Shot list

| # | On screen | Command / action | Caption | ~s |
|---|---|---|---|---|
| 1 | title card | — | heddle — contracts are warp, code is weft | 2 |
| 2 | benchmark table | `uv run python bench/benchmark.py` | 5.5× fewer tokens per regeneration | 5 |
| 3 | the ask | Claude Code: "re-implement `revenue_by_region`" | the agent asks heddle, not the filesystem | 3 |
| 4 | `get_contract` | MCP `get_contract("revenue_by_region")` → packet | one ~300-token packet: spec + dep signatures + callers | 5 |
| 5 | the weave | agent edits `src/revenue.py::revenue_by_region` | it weaves the weft | 4 |
| 6 | `verify` (miss) | MCP `verify(["revenue_by_region"])` → `pass` | hash-keyed verification — pytest only on a miss | 5 |
| 7 | `verify` (hit) | `verify` again → `cached-pass` | second run: cached-pass, no pytest | 3 |
| 8 | `status` | MCP `status()` → token counters | the whole loop, in a few hundred tokens | 4 |

## Mirror the MCP calls on the CLI (if not screen-recording Claude Code)

```bash
heddle verify revenue_by_region        # scene 6: pass  (runs pytest)
heddle verify revenue_by_region        # scene 7: cached-pass
heddle status                          # scene 8: cache hit-rate + resolved interpreter
```

The CLI mirror covers scenes 6 and 7 faithfully, but `heddle status` on the CLI
reports `tokens: 0`: the token counters are incremented only by the MCP server
(`src/heddle/server.py`), so scene 8's token-counter payoff needs the Claude Code
(MCP) path, not this mirror.

## Captions (one line each, ≥1.5 s on screen)
- Contracts are the durable warp; code is regenerable weft.
- Regenerating a unit usually means re-reading whole spec + source files.
- heddle serves the exact dependency closure as one small packet …
- … and a cached pass/fail instead of re-running the suite.
- 5.5× fewer tokens, verified.

## Recording tips
- Scene 2's benchmark rebuilds and warms `examples/sales/.heddle`, so don't wipe
  the store after it. Scene 5's edit to `src/revenue.py::revenue_by_region` busts
  only that unit's impl hash, so scene 6 verifies it cold (a real pytest `pass`),
  scene 7 reuses the cache, and scene 8's `status` stays clean (`dirty: 0`).
  Re-indexing the whole store instead leaves every other contract `dirty` and
  makes scene 8 a wall of red.
- Trim dead time between commands; end on the `status` counters or the benchmark
  table — the number is the hook.
