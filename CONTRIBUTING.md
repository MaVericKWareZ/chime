# Contributing to chime

Thanks for thinking about contributing! chime is small and the bar is friendly — bug reports, docs fixes, and small features are all welcome.

## Quick start

```bash
git clone https://github.com/MaVericKWareZ/chime
cd chime
python -m venv .venv && source .venv/bin/activate
make install   # editable install with dev deps + pre-commit hooks
make test
```

`make help` lists every dev/release/build target the project supports — that's the canonical reference, not this document.

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

The version is derived from the git tag at build time (hatch-vcs), so there's
no version string to edit. Just:

```bash
make release          # patch bump (most common)
make release-minor    # minor bump
make release-major    # major bump
# or, for an explicit version:
python scripts/release.py 0.5.0
```

The helper validates the working tree and branch, confirms main CI is green,
rewrites `CHANGELOG.md`, shows the planned edits, asks for confirmation,
commits, pushes, waits for CI on the new commit, tags `vX.Y.Z`, pushes the
tag, and (unless `--no-brew-bump`) triggers the homebrew-tap bump workflow.
Add `--dry-run` to preview without writing — or just `make release-dry`.

The actual publish work is done by `.github/workflows/release.yml`, which fires
when the `v*.*.*` tag is pushed: build → PyPI via trusted publishing → GitHub
release.

First-time PyPI setup: register the project at
<https://pypi.org/manage/account/publishing/> with `owner=<your gh user>`,
`repo=chime`, `workflow=release.yml`, `environment=pypi`.
