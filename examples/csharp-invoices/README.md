# csharp-invoices — the C# example

11 contracts over a billing run, three dependency layers deep: record types
(`Customer`, `LineItem`, `Invoice`) → pricing and charge arithmetic → invoice
assembly, rendering, and run totals. It has the shape of a small service layer
with zero framework dependencies — xUnit via `dotnet test` is the entire
toolchain. The `.cs` impl extension routes every unit through the C# adapter:
hashing via a Roslyn token-stream helper the adapter compiles once with the
SDK's own `csc`, verification through `dotnet test` on this project's
[invoices.csproj](invoices.csproj) (NUnit and MSTest projects ride the same
VSTest filter; an xunit-v3 / Microsoft.Testing.Platform project runs too —
whole-suite, see the adapter notes in the repo README).

Commands assume `hashloom` is on PATH (`pip install hashloom`). Working from
this repo's checkout instead, prefix every `hashloom` command with `uv run`.

## Prerequisites

- the .NET SDK >= 8 (`dotnet` on PATH, or `.hashloom/config.json` →
  `{"dotnet": "..."}`); the csproj targets net8.0 with `RollForward: Major`,
  so an SDK-9-only machine runs it on its newer runtime
- network on first run (NuGet restores xUnit and the test SDK)

## Run the tests directly

```bash
dotnet test
```

## The hashloom loop

```bash
hashloom init && hashloom index      # derive the store from contracts/
hashloom verify --radius Customer LineItem Invoice DiscountCents TaxCents FormatCents
hashloom status                      # dirty units, cache hit-rate
```

Those six roots cover the whole graph, so the first `verify` runs `dotnet
test` for all 11 units; run it again and every unit returns `cached-pass`
without executing a single test — worth having in C#, where each miss pays an
MSBuild round trip.

## Watch a change find its blast radius

Edit the body of `DiscountCents` in [src/Charges.cs](src/Charges.cs) — adjust
a bracket divisor — then:

```bash
hashloom verify --radius DiscountCents
```

Exactly one unit re-runs, and it *fails* its bracket table — the summary names
the exact `[Theory]` case that broke — and the CLI exits nonzero. Meanwhile
`InvoiceFor` stays `cached-pass`: it leans on `DiscountCents`'s *contract*,
which didn't change. Revert the edit and everything is `cached-pass` again.
Reformatting, comments, and XML-doc edits change no hash at all — the Roslyn
token stream sees through them. The contracts also exercise the adapter's
C#-specific addressing: `Class.Method` impl quals, records hashed whole, and
dotted test node ids into the nested class in
[BillingTests.cs](tests/BillingTests.cs) (the runtime's `Outer+Inner`
spelling; namespaces never appear in node ids). With no committed
`packages.lock.json`, the toolchain identity stays version-only — commit one
and the declared dependency set joins the verification key.

## Point an agent at it

```bash
hashloom serve    # MCP over stdio: get_contract, put_contract, get_dependents, verify, status
```

The agent workflow and working rules live in
[docs/getting-started.md](../../docs/getting-started.md); the token accounting
for this project is in [docs/benchmarks.md](../../docs/benchmarks.md).
