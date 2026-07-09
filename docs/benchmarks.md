# Benchmarks — the scorecard

Every token-reduction number hashloom publishes, in one place: what was measured,
on what project, when, under which hashloom version. **Every row is reproducible
from this repo** — the projects are in `examples/`, the scripts in `bench/`.

All ratios are deterministic token counts — both sides of every comparison are
counted with the same tiktoken encoder (`cl100k`). They do not depend on which
AI model (or human) drives the session, only on the project's shape and the
hashloom version.

## Headline numbers

| scenario | scope | raw tokens | hashloom tokens | ratio | median/unit | date | hashloom |
|---|---|--:|--:|--:|--:|---|---|
| sales (Python) — the DoD gate | 3 regeneration tasks over 20 contracts | 6,004 | 1,117 | **5.4×** | — | 2026-07-04 | 0.3.0 |
| sales (Python) — full sweep | all 19 verifiable units | 31,495 | 7,618 | **4.1×** | 4.8× | 2026-07-04 | 0.3.0 |
| go-ledger (Go) — full sweep | all 8 units | 6,656 | 2,201 | **3.0×** | 3.3× | 2026-07-04 | 0.3.0 |
| ts-cart (TypeScript) — full sweep | all 8 units | 6,400 | 2,087 | **3.1×** | 3.4× | 2026-07-04 | 0.3.0 |
| java-payroll (Java) — full sweep | all 11 units | 9,670 | 3,036 | **3.2×** | 2.8× | 2026-07-08 | unreleased |

Two different measurements, deliberately: the **DoD gate**
(`bench/benchmark.py`, enforced in CI, exits nonzero below 5×) measures three
representative regeneration tasks, one per dependency layer. The **full sweeps**
(`bench/sweep.py`) regenerate *every* unit once — including the leaf types that
barely benefit — so a sweep always averages lower than the gate. That is not a
regression; it is the honest cost of counting everything.

Raw-side counts reproduce exactly; hashloom-side totals jitter by ~1 token per
unit between runs (verify statuses flip `pass` → `cached-pass`), so per-unit
last decimals move while the ratios hold.

## What one number hides: the distribution

The ratio tracks dependency depth — the more transitive closure a unit has,
the more a ~300-token packet replaces:

- **sales**: `top_customers` 6.2×, `average_sale` 6.1×, `segment_revenue_share`
  5.8× at the deep end; the `Sale` type itself 1.0× at the leaf end (its raw
  files were already packet-sized).
- **go-ledger**: `Balanced` 4.8× down to `Account` 1.2×.
- **ts-cart**: `totalCents` 5.0× down to `Sku` 1.5×.
- **java-payroll**: `slipFor` 5.4× down to `PaySlip` 1.4×. (Maven's quiet
  mode prints nothing on a green suite, so the raw baseline gets *zero*
  suite-output tokens here — the Java row is the most conservative of the four.)

The examples are deliberately small (8–20 contracts, 2–3 layers), so their
sweeps sit in the 3–4× range. Deeper projects score higher, not lower: every
additional dependency layer widens the gap between reading a closure and
reading a packet. The DoD gate's 5.4× on three mid-to-deep units shows the
same effect inside one project.

## Cache economics (from a real store, not a benchmark)

Verification caching is the other half of the payoff. This repo dogfoods
hashloom (12 contracts over its own stable seams — see `contracts/`), and its
store counters after day one:

| store | verify requests | served from cache | test runs avoided | hit rate |
|---|--:|--:|--:|--:|
| hashloom-on-hashloom | 43 | 31 | 31 | 72% |

Counters are cumulative and advance with use (`hashloom status` shows them);
reproduce by cloning the repo and verifying the contracts yourself.

One accounting caveat: `status`'s cumulative **token counters populate only via
the MCP server** (`_respond` in `server.py` counts every tool response); CLI
use exercises the cache counters but not the token counters.

## What the numbers claim — and what they don't

The methodology (`bench/benchmark.py` and `bench/sweep.py`, same accounting):
**raw mode** counts what a file-based agent reads to regenerate one unit — the
spec and full source file of the unit *and* of every transitive dependency,
the unit's own tests, and one full test-suite run's output at the runner's
defaults (pytest / `go test ./...` / `node --test`) — except Java, where the
runner is `mvn --batch-mode -q test`: Maven's default INFO logging would
inflate the raw baseline, so the Java row runs quiet and a green suite
contributes *zero* suite-output tokens (see the distribution note above).
**Hashloom mode** counts
the JSON of three tool responses: `get_contract`,
`get_dependents(transitive=true)`, `verify`.

Read the numbers with these concessions attached:

- **The baseline is granted free, perfect knowledge of the dependency
  closure** — no grep, no wrong-file reads, no discovery cost. That is
  deliberately generous to the baseline, since computing the closure is
  precisely what hashloom does; a real file-based agent pays discovery on top.
- **The hashloom side assumes first-try-green regeneration** from the packet
  alone — no failure/iteration loop, no re-reading tests — and MCP session
  overhead (tool schemas, call inputs) is uncounted.
- **It is a per-change maintenance estimate, not a session total.** Repeated
  edits in one session amortize raw file reads; conversely, every fresh
  session pays them again.
- **The initial build is not measured and costs *more* with hashloom** —
  contracts are authored on top of the code and tests. The payoff is at
  maintenance and regeneration time.
- A green suite prints little, so the suite-output component is small in
  every row above; a failing raw run would dump tracebacks where hashloom
  serves a ≤40-token summary, so the failure-path advantage is invisible in
  these numbers.

## Reproduce

```bash
# the DoD gate (CI runs this on every push; exits nonzero below 5x)
uv run python bench/benchmark.py

# full sweeps — any hashloom project works, including yours
uv run python bench/sweep.py examples/sales
uv run python bench/sweep.py examples/go-ledger     # needs a Go toolchain
uv run python bench/sweep.py examples/ts-cart       # npm install there first; Node >= 22.6
uv run python bench/sweep.py examples/java-payroll  # needs a JDK >= 17 and Maven
```

New scenario runs belong in the table above — record the scope, date, and
hashloom version.
