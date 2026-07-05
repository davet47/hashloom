# Releasing heddle

heddle ships to PyPI as the distribution `heddle-mcp` (the bare `heddle` name is
held by a third-party placeholder). The import name and CLI stay `heddle`, so
users run `pip install heddle-mcp`, then `heddle serve` / `import heddle`.

Releases publish automatically via GitHub Actions Trusted Publishing (OIDC, no
stored token): pushing a `v*` tag runs `.github/workflows/release.yml`, which
builds the sdist + wheel and uploads them to PyPI. The maintainer never runs
`twine`. After the PyPI publish succeeds, an `mcp-registry` job (GitHub OIDC
again, no stored secret) syncs the versions in `server.json` from the tag and
updates the listing on registry.modelcontextprotocol.io. The build job fails
fast if the tag and `__version__` disagree, since PyPI publishes `__version__`
while the registry listing is stamped from the tag.

0.1.0 shipped on 2026-06-23. The PyPI pending publisher is registered, so
subsequent releases need only a version bump and a tag.

## Cut a release

1. Bump `__version__` in `src/heddle/__init__.py` (the single source of truth;
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
   That fires `release.yml`: the build job produces `dist/heddle_mcp-X.Y.Z*`,
   the publish job uploads them over OIDC, and the mcp-registry job refreshes
   the MCP Registry listing. Watch the Actions tab.
5. Verify it is live:
   ```bash
   uvx --from heddle-mcp heddle --version   # -> heddle X.Y.Z
   curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.davet47/heddle"   # listing shows X.Y.Z
   ```

## Trusted Publishing setup (one-time, already done)

Registered at pypi.org, Account settings, Publishing, "Add a pending publisher":
project `heddle-mcp`, owner `davet47`, repo `heddle`, workflow `release.yml`,
environment `pypi`. The publish job declares `id-token: write` and
`environment: pypi`, so PyPI mints a short-lived token for that exact run.

## Notes

- `dist/` is gitignored, so build artifacts are produced in CI and never
  committed.
- The README is the PyPI long description, so image links must be absolute URLs.
  A relative path renders on GitHub but breaks on the PyPI project page.
- README and summary changes only appear on the PyPI page on the next release;
  a published version's description is frozen at upload time.
