# Launch announcement drafts

Per the launch plan: post these **after** the README demo gif is recorded and
0.1.0 is on PyPI. Two audiences — Hacker News (Show HN) and the Spec Kit
discussions. Honest and hype-free; the number does the selling.

---

## Hacker News — Show HN

**Title:**

> Show HN: Heddle – a hash-keyed verification cache for spec-driven agent loops

**Body:**

> Heddle is an MCP server that makes the regenerate-and-verify loop cheap for
> coding agents.
>
> The idea: in spec-driven development the **contract** (a small YAML spec) is the
> durable artifact and the **code** is regenerable. Heddle content-addresses each
> contract, and caches verification keyed by the hash of `(contract,
> implementation, transitive dependency contracts)`. So when an agent
> re-implements a unit, it asks heddle for a ~300-token context packet — the
> spec, its dependencies' signatures, and its callers — instead of re-reading
> whole files, and gets a cached `pass`/`fail` instead of re-running the test
> suite. pytest only runs on a real cache miss.
>
> On a 20-contract sample, three regeneration tasks cost **5.5× fewer tokens**
> through heddle than reading raw files. The baseline is deliberately generous —
> it assumes the agent already knows the exact dependency closure, which is the
> thing heddle computes for you.
>
> v0.1 is Python-only, single-process, Apache-2.0. Five MCP tools, five CLI
> commands — the README is the entire surface. The name's from weaving: contracts
> are the fixed **warp**, code is the **weft** woven through.
>
> `pip install heddle` · https://github.com/davet47/heddle

---

## Spec Kit discussions

**Title:** A caching + verification layer for spec-driven loops

**Body:**

> Spec-driven tooling made specs the source of truth and code regenerable — but
> most of it runs on plain files, which leaves three costs on the table:
>
> 1. **Context acquisition is expensive** — re-reading whole spec + source files
>    to regenerate one unit.
> 2. **Verification is uncached** — re-running the full relevant test surface even
>    when nothing in a contract's dependency closure changed.
> 3. **Blast radius is by convention, not mechanism** — nothing tells the agent
>    precisely which dependents a spec change invalidates.
>
> Heddle is a small MCP server that addresses those three directly:
> content-addressed contracts, a hash-keyed verification cache, and a
> `get_dependents` blast-radius query. It's complementary to a spec workflow
> rather than a replacement — point any agent at it over MCP. Early benchmark is
> ~5.5× token reduction on regeneration tasks.
>
> Would love feedback on the contract format and the hashing semantics — in
> particular, what should count as a *meaning* change (re-verify) vs. a *cosmetic*
> one (cache holds): today that's signature + invariant/example order vs.
> whitespace, key order, comments, docstrings, and file relocation.

---

## Notes

- Lead with the mechanism + the number; HN distrusts adjectives.
- Link straight to the README — its "The number" table and the 5-tool surface are
  the pitch.
- Have the demo gif embedded under the badge before posting (ISSUES #8,
  [docs/demo.md](demo.md)).
