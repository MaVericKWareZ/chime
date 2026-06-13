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

1. Bump `__version__` in `src/chime/__init__.py`.
2. Move `CHANGELOG.md` `[Unreleased]` content under a new version heading.
3. Commit, then `git tag vX.Y.Z && git push --tags`.
4. The release workflow builds and publishes to PyPI via trusted publishing, then creates a GitHub release.

First-time PyPI setup: register the project at <https://pypi.org/manage/account/publishing/> with `owner=<your gh user>`, `repo=chime`, `workflow=release.yml`, `environment=pypi`.
