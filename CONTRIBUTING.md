# Contributing to chime

Thanks for thinking about contributing! chime is small and the bar is friendly — bug reports, docs fixes, and small features are all welcome.

## Quick start

```bash
git clone https://github.com/MaVericKWareZ/chime
cd chime
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
pytest
```

## Making a change

1. Open an issue first for anything non-trivial — saves wasted work.
2. Branch from `main`.
3. Add a test if you're changing behavior.
4. Run `ruff check . && ruff format . && pytest` before pushing.
5. Update `CHANGELOG.md` under `[Unreleased]`.
6. Open a PR — CI runs lint + tests on macOS and Linux across supported Python versions.

## Code style

- Ruff handles lint + format. The config is in `pyproject.toml`.
- Type hints encouraged but not enforced (no mypy gate yet).
- Pure functions belong in `parsers.py`; side-effecting OS calls belong in `alerts.py` or `state.py`. Keep `cli.py` for argparse plumbing and user-facing output.

## Adding platform support

`alerts.py` dispatches on `sys.platform`. To add Windows or BSD support, extend `notify()`, `play_sound()`, `speak()`, and `list_sounds()` with the appropriate backend.

## Releasing (maintainers)

The fast path is the helper script:

```bash
python scripts/release.py 0.2.0
```

It validates the working tree and branch, confirms main CI is green, rewrites
`src/chime/__init__.py` and `CHANGELOG.md`, shows the planned edits, asks for
confirmation, commits, pushes, waits for CI on the new commit, tags `v0.2.0`,
pushes the tag, and (unless `--no-brew-bump`) triggers the homebrew-tap bump
workflow. `--dry-run` shows planned edits without writing.

The actual publish work is done by `.github/workflows/release.yml`, which fires
when the `v*.*.*` tag is pushed: build → PyPI via trusted publishing → GitHub
release.

If you prefer to do it by hand:

1. Bump `__version__` in `src/chime/__init__.py`.
2. Promote the `CHANGELOG.md` `[Unreleased]` block to a dated `[X.Y.Z]` section
   and refresh the link footer.
3. Commit, push, wait for CI to pass on `main`.
4. `git tag vX.Y.Z && git push --tags`.

First-time PyPI setup: register the project at
<https://pypi.org/manage/account/publishing/> with `owner=<your gh user>`,
`repo=chime`, `workflow=release.yml`, `environment=pypi`.
