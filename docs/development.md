# Development and local builds

Use a source checkout and Python 3.10 or newer. Install Node.js for the browser
logic tests. All scientific fixtures in the test suite are synthetic.

```bash
python -m pip install -e '.[dev]'
node --version
python -m pytest
python -m ruff check src tests scripts
```

Tests create temporary packages and local HTTP servers. The CI matrix covers
Python 3.10–3.14 on Linux, with Windows and macOS jobs on Python 3.13. A separate
Python 3.10 job exercises the direct runtime dependency minima together using
`tests/minimum-requirements.txt`. `uv lock --check` verifies the development lock;
`uv sync --extra dev --locked` installs that environment.

## Build and verify distributions

Start with an empty `dist/` directory. The default build creates an sdist, then
builds the wheel from that sdist.

```bash
python -m build
python -m twine check --strict dist/*
```

The wheel contains the runtime, GUI, skill, schemas, rules and templates.
The sdist also includes synthetic tests, fixtures, examples and build helpers.
Tutorial screenshots and downloads ship separately.

Install the wheel into a fresh virtual environment and run the installed-package
check with that environment's Python:

```bash
python -m venv wheel-env
wheel-env/bin/python -m pip install dist/claimtrace-1.0-py3-none-any.whl
wheel-env/bin/python scripts/smoke_installed.py
```

On Windows, use `wheel-env\Scripts\python.exe`. The check exercises CLI review
and export, agent proposal review, skill export, GUI assets and the local state
endpoint. It asserts that imports come from the selected environment. Extract
the sdist separately and run `python -m pytest` from its root to verify the
source package and fixtures.

## Prepare release downloads

From the full repository checkout, use a fresh output directory:

```bash
python scripts/build_release_assets.py --dist dist --out release-assets
```

This copies the already built wheel and sdist, then creates the skill and tutorial
ZIPs. `SHA256SUMS` lets recipients verify these exact downloads. The tutorial
archive keeps its local links, screenshot folders, data-source records and
licenses together. Extract it and open `index.html` to start reading.

The `python-package-distributions` CI artifact contains only the wheel and
sdist. `release-downloads` contains all five release files. Use the same Python
distribution files for PyPI and the GitHub release.

## Version and publishing configuration

Keep `project.version`, `PACKAGE_VERSION` and the lockfile version aligned.
Product version `1.0` uses Git tag `v1.0`. Schema and agent protocol versions
follow their [own compatibility contracts](interfaces.md).

The existing `.github/workflows/ci.yml` publishes version tags through the
`pypi` environment after test and build jobs succeed. PyPI Trusted Publishing
binds the repository, workflow filename and environment. Preserve that identity
when editing CI, or update the publisher settings when changing it. See
[PyPI's publisher configuration guide](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).
Tag creation, tag push, environment approval and publication are separate
maintainer actions.
