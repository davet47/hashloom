# Getting started: building a package contract-first with an agent

The README explains what heddle is. This is the other half: how a human and a
coding agent actually work with it, day to day. The short version — the human
owns the contracts, the agent owns the code, and `verify --radius` decides when
anything is done.

## 1. Set up a project

```bash
pip install heddle-mcp          # or: uvx --from heddle-mcp heddle ...
mkdir mypackage && cd mypackage
heddle init                     # creates .heddle/ and contracts/
```

Point your agent at it. For Claude Code:

```bash
claude mcp add heddle -- heddle serve
```

Start agent sessions from inside the project: the server resolves the project
by walking up from its working directory to the nearest `.heddle/`. If
`heddle status` shows the wrong interpreter for your tests, set it explicitly
(`.heddle/config.json` → `{"python": "..."}`); non-Python toolchains resolve
the same way per impl extension (`"go"`, `"node"`, `"java"`).

## 2. Give the agent the working rules

Drop this in the project's `CLAUDE.md` (or your agent's equivalent). It is the
piece that changes the agent's behaviour from file-first to contract-first —
copy it, but read the loop below so you know what you're enforcing:

```markdown
# Working rules

This package is built heddle-first. Contracts are warp; code is weft.

- Design each unit as a contract BEFORE implementing it: `put_contract` with
  signature, invariants, examples, deps, tests, impl — and `status: inferred`
  on any contract you derived rather than the human specified. The human flips
  it to confirmed on review.
- To (re)implement a unit, `get_contract` for the ~300-token packet. Do not
  re-read source files you can regenerate from the contract.
- Before changing a contract, `get_dependents` to see the blast radius. After
  changing anything, `verify` with `radius=true` on what you touched must
  return `ok: true`. That gate is the definition of done for every task.
- Tests are the machine check: write them with the contract, not after the
  implementation. An impl without tests cannot claim green.
```

## 3. The loop, once through

Say you ask for a rate limiter. A heddle-first agent works it like this:

**Contracts first.** The agent designs the seams and puts each one — marking
what it invented, not you, as `inferred`:

```yaml
name: allow
signature: "(bucket: Bucket, now: float) -> bool"
deps: [Bucket, refill]
invariants:
  - never lets the bucket go below zero tokens
examples:
  - in: "bucket with 1 token"
    out: "True, and the token is spent"
tests: [tests/test_limiter.py::test_allow_spends_tokens]
impl: src/limiter.py::allow
status: inferred
```

The `put_contract` response echoes `"inferred": true` — heddle has recorded
that this spec is the agent's guess at your intent, not your word.

**You review the seams, not the code.** `heddle status` lists every `inferred`
contract — that list is your review queue. Review a contract the way you review
an interface: is the signature right, are the invariants what you meant? Fix
what's wrong; for what's right, delete the `status: inferred` line (or set
`confirmed`). The flip is free by design — status is provenance, not meaning,
so nothing re-verifies and no cache busts:

```json
{"name": "allow", "changed": false, "invalidated": [],
 "diff": {"status": {"old": "inferred", "new": "confirmed"}}}
```

**The agent implements from packets.** To write or rewrite a unit it calls
`get_contract` — the contract, its hash, one-line signatures of its deps, and
its callers, a few hundred tokens — instead of re-reading the file closure.
The code is weft: regenerated freely, never precious.

**The gate decides done.** After any change:

```bash
heddle verify --radius allow      # or the MCP verify with radius=true
```

One call verifies the unit plus everything it invalidates, serves cached greens
for whatever nothing busted, runs tests for the rest, and returns a single
`ok: true|false` (the CLI exits nonzero on false — the same gate works in CI or
a pre-commit hook). Until an inferred contract is confirmed, every verify and
blast-radius answer that rests on it carries an `inferred` flag: advisory,
never an error, but visible.

**Contract changes announce their blast radius.** When you later change a
confirmed contract — a signature, an example — the `put_contract` response
names every dependent it invalidated, and the radius gate re-proves exactly
those. Nothing else re-runs.

## 4. Where heddle earns its keep — and where it doesn't

Contracts belong on stable seams: interfaces other units depend on that you
expect to outlive their current implementation. A package with ten-plus units
and layered dependencies pays for the ceremony many times over in cached
verification and small context packets. A three-function utility does not —
just write it. And resist pinning interiors you would happily rewrite: dropping
a contract where it earns no place is correct use, not a failure.

## 5. Where to go next

- **Reference projects** — [`examples/sales`](../examples/sales) (Python, 20
  contracts), [`examples/go-ledger`](../examples/go-ledger) (Go), and
  [`examples/ts-cart`](../examples/ts-cart) (TypeScript): the same loop in each
  language, one adapter per impl extension.
- **Team scale** — point `.heddle/config.json` at a shared cache
  (`{"shared": {"url", "token"}}`, backend: `python -m heddle.cache_server`)
  and one teammate's or CI's green serves everyone, keyed by toolchain so a
  3.11 pass never serves 3.13.
- **The spec** — [README](../README.md) for the full tool surface and the
  hashing semantics that decide what re-verifies (meaning) and what stays
  cached (everything else).
