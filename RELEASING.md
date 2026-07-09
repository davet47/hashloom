# Releasing hashloom

hashloom ships to PyPI as the bare distribution `hashloom` — name, import, and
CLI all match: `pip install hashloom`, then `hashloom serve` / `import hashloom`.
(Releases 0.1.0-0.3.3 shipped as `heddle-mcp`, before the rename; that project
is frozen with a tombstone pointing here.)

Releases publish automatically via GitHub Actions Trusted Publishing (OIDC, no
stored token): pushing a `v*` tag runs `.github/workflows/release.yml`, which
builds the sdist + wheel and uploads them to PyPI. The maintainer never runs
`twine`. After the PyPI publish succeeds, an `mcp-registry` job (GitHub OIDC
again, no stored secret) syncs the versions in `server.json` from the tag and
updates the listing on registry.modelcontextprotocol.io. The build job fails
fast if the tag and `__version__` disagree, since PyPI publishes `__version__`
while the registry listing is stamped from the tag.

The PyPI pending publisher for `hashloom` is bound to `davet47/hashloom` +
`release.yml` + environment `pypi` (registered at the 0.4.0 rename; the old
`heddle-mcp` publisher retired with its tombstone). Subsequent releases need
only a version bump and a tag.

## Cut a release

1. Bump `__version__` in `src/hashloom/__init__.py` (the single source of truth;
   the wheel version derives from it via hatchling). The tag only triggers the
   workflow, so the tag and `__version__` must match.
2. Confirm green locally (CI runs both on the PR too):
   ```bash
   uv run pytest
   uv run python bench/benchmark.py    # must stay >5x (exits nonzero below)
   ```
3. Land the version bump on `main` through a PR.
4. Tag and push from a synced `main`:
   ```bash
   git switch main && git pull
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
   That fires `release.yml`: the build job produces `dist/hashloom-X.Y.Z*`,
   the publish job uploads them over OIDC, and the mcp-registry job refreshes
   the MCP Registry listing. Watch the Actions tab.
5. Verify it is live:
   ```bash
   uvx --from hashloom hashloom --version   # -> hashloom X.Y.Z
   curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.davet47/hashloom"   # listing shows X.Y.Z
   ```

## Trusted Publishing setup (one-time, already done)

Registered at pypi.org, Account settings, Publishing, "Add a pending publisher":
project `hashloom`, owner `davet47`, repo `hashloom`, workflow `release.yml`,
environment `pypi`. The publish job declares `id-token: write` and
`environment: pypi`, so PyPI mints a short-lived token for that exact run.

## Notes

- `dist/` is gitignored, so build artifacts are produced in CI and never
  committed.
- The README is the PyPI long description, so image links must be absolute URLs.
  A relative path renders on GitHub but breaks on the PyPI project page.
- README and summary changes only appear on the PyPI page on the next release;
  a published version's description is frozen at upload time.
