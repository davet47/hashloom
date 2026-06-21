# Releasing heddle

Cutting a release to PyPI. Requires a PyPI account with an API token. The
maintainer runs the upload by hand — CI does not publish.

## Steps

1. Bump `version` in `pyproject.toml` (skip for the first `0.1.0` cut).
2. Confirm green — CI runs both, but check locally too:
   ```bash
   uv run pytest
   uv run python bench/benchmark.py    # must stay >5x (exits nonzero below)
   ```
3. Build clean artifacts:
   ```bash
   rm -rf dist/
   uv build                            # -> dist/heddle-<version>-py3-none-any.whl + .tar.gz
   ```
4. Validate metadata + README rendering:
   ```bash
   uvx twine check dist/*
   ```
5. Smoke-test the wheel in a throwaway venv:
   ```bash
   python3 -m venv /tmp/heddle-smoke
   /tmp/heddle-smoke/bin/pip install dist/heddle-*.whl
   /tmp/heddle-smoke/bin/heddle --help
   ```
6. (Optional) Dry-run via TestPyPI, then install from it:
   ```bash
   uvx twine upload --repository testpypi dist/*
   pip install --index-url https://test.pypi.org/simple/ \
               --extra-index-url https://pypi.org/simple/ heddle
   ```
7. Publish:
   ```bash
   uvx twine upload dist/*
   ```
   Auth with a PyPI API token — username `__token__`, password `pypi-…`
   (or `TWINE_USERNAME` / `TWINE_PASSWORD`, or `~/.pypirc`).
8. Tag it: `git tag v<version> && git push --tags`.

`dist/` is gitignored — build artifacts never get committed.
