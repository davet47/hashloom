# Launch announcement drafts

**Ready to post:** 0.1.0 is live on PyPI and the demo gif is embedded in the
README, so both gates are cleared. Two audiences: Hacker News (Show HN) and the
Spec Kit discussions. Honest and hype-free; the number does the selling.

---

## Hacker News (Show HN)

HN does not render Markdown (no bold, no inline code), so this body is plain
text and raw URLs auto-link. Paste it as-is.

**Title:**

> Show HN: Heddle, content-addressed contracts for spec-driven agent loops

**Body:**

> Heddle treats software units as content-addressed contracts rather than files. It's an MCP server for spec-driven agent loops.
>
> A contract is a small YAML spec (signature, invariants, examples, dependency names) and the code behind it is regenerable. Heddle hashes each contract and knows its dependencies, so the structure an agent keeps re-deriving from files is something it computes once and serves. Build systems ask which files changed. Heddle asks which software obligations changed.
>
> That buys three things. Verification caching: a green result is keyed on the contract, implementation, and dependency hashes and served from cache until one of them changes, so pytest runs only on a real miss. Precise blast radius: a contract change reports exactly which dependents it invalidates, by hash. And tiny context packets: to re-implement a unit, an agent asks heddle for a ~300-token packet (the spec, its dependencies' signatures, and its callers) instead of re-reading whole files.
>
> On a 20-contract sample, three regeneration tasks cost 5.5x fewer tokens through heddle than reading raw files. The baseline is deliberately generous: it assumes the agent already knows the exact dependency closure, which is the thing heddle computes for you.
>
> v0.1 is Python-only, single-process, Apache-2.0. Five MCP tools, five CLI commands, and the README is the entire surface. The name is from weaving: contracts are the fixed warp, code is the weft woven through.
>
> pip install heddle-mcp · https://github.com/davet47/heddle

---

## Spec Kit discussions

**Title:** A caching + verification layer for spec-driven loops

**Body:**

> Spec-driven tooling made specs the source of truth and code regenerable, but
> most of it runs on plain files, which leaves three costs on the table:
>
> 1. **Context acquisition is expensive.** Re-reading whole spec and source
>    files to regenerate one unit.
> 2. **Verification is uncached.** Re-running the full relevant test surface
>    even when nothing in a contract's dependency closure changed.
> 3. **Blast radius is by convention, not mechanism.** Nothing tells the agent
>    precisely which dependents a spec change invalidates.
>
> Heddle treats each software unit as a content-addressed contract with explicit
> dependencies, and addresses those three directly: a hash-keyed verification
> cache, a `get_dependents` blast-radius query, and a small context packet per
> unit. It's complementary to a spec workflow rather than a replacement, so you
> point any agent at it over MCP. Early benchmark is ~5.5x token reduction on
> regeneration tasks.
>
> Would love feedback on the contract format and the hashing semantics, in
> particular what should count as a *meaning* change (re-verify) versus a
> *cosmetic* one (cache holds). Today the contract hash covers the signature and
> the invariant and example order; whitespace, key order, comments, docstrings,
> and file relocation are excluded. Invariants are free text inside the hash, so
> rewording one still re-verifies dependents, which we want to sharpen.

---

## Notes

- Lead with the mechanism + the number; HN distrusts adjectives.
- Link straight to the README — its "The number" table and the 5-tool surface are
  the pitch.
- Demo gif is embedded under the badge (ISSUES #8, [docs/demo.md](demo.md)) and
  0.1.0 is on PyPI, so both posting gates are cleared.
