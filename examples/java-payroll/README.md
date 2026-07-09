# java-payroll — the Java example

11 contracts over a weekly payroll run, three dependency layers deep: record
types (`Employee`, `TimeSheet`, `PaySlip`) → pay and tax arithmetic → payslip
rendering and run totals. It has the shape of a Spring service layer with zero
framework dependencies — JUnit 5 via Maven is the entire toolchain. The
`.java` impl extension routes every unit through the Java adapter: hashing via
a single-file `javac`-tree helper, verification through this project's own
build (`pom.xml` → Maven; a Gradle project auto-detects the same way).

Commands assume `heddle` is on PATH (`pip install heddle-mcp`). Working from
this repo's checkout instead, prefix every `heddle` command with `uv run`.

## Prerequisites

- a JDK >= 17 (`java` on PATH, or `.heddle/config.json` → `{"java": "..."}`;
  the adapter itself needs only >= 11 — 17 is this project's `pom.xml` floor,
  for records)
- Maven (`mvn` on PATH; the first run downloads JUnit from Maven Central)

## Run the tests directly

```bash
mvn test
```

## The heddle loop

```bash
heddle init && heddle index        # derive the store from contracts/
heddle verify --radius Employee TimeSheet PaySlip withholdingCents formatCents
heddle status                      # dirty units, cache hit-rate
```

Those five roots cover the whole graph, so the first `verify` runs Maven for
all 11 units; run it again and every unit returns `cached-pass` without
executing a single test — worth having in Java, where a JVM-and-Maven round
trip is the priciest suite start of the four examples.

## Watch a change find its blast radius

Edit the body of `withholdingCents` in
[src/main/java/payroll/Tax.java](src/main/java/payroll/Tax.java) — adjust a
bracket — then:

```bash
heddle verify --radius withholdingCents
```

Exactly one unit re-runs, and it *fails* its bracket table: the contract
caught the change, and the CLI exits nonzero. Meanwhile `netCents` and
`slipFor` stay `cached-pass` — they lean on `withholdingCents`'s *contract*,
which didn't change. Revert the edit and everything is `cached-pass` again.
Reformatting, comments, and javadoc change no hash at all — the `javac` tree
sees through them. The contracts also exercise the adapter's Java-specific
addressing: `Class.method` impl quals, and dotted test node ids into the
`@Nested` class in [PayrollTest.java](src/test/java/payroll/PayrollTest.java).

## Point an agent at it

```bash
heddle serve    # MCP over stdio: get_contract, put_contract, get_dependents, verify, status
```

The agent workflow and working rules live in
[docs/getting-started.md](../../docs/getting-started.md); the token accounting
for this project is in [docs/benchmarks.md](../../docs/benchmarks.md).
