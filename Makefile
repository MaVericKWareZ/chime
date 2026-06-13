.DEFAULT_GOAL := help
SHELL := /bin/bash
PY ?= python3

.PHONY: help install test test-cov lint fmt build clean smoke \
        release release-patch release-minor release-major release-dry \
        brew-bump

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ { \
		printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 \
	}' $(MAKEFILE_LIST)

# ---------- dev loop ----------

install:  ## Editable install with dev deps + pre-commit hooks
	$(PY) -m pip install -e ".[dev]"
	pre-commit install 2>/dev/null || true

test:  ## Run the test suite
	pytest

test-cov:  ## Tests with coverage report
	pytest --cov=chime --cov-report=term-missing

lint:  ## Lint and format-check (no changes)
	ruff check .
	ruff format --check .

fmt:  ## Auto-fix lint findings and reformat
	ruff check --fix .
	ruff format .

smoke:  ## Quick end-to-end check of the installed chime command
	chime version
	chime help > /dev/null
	chime --no-sound --bg 2s "make smoke test"
	@sleep 1 && chime list
	@sleep 3 && chime list

# ---------- packaging ----------

build:  ## Build sdist + wheel (hatch-vcs picks the version from git)
	rm -rf dist build
	$(PY) -m build

clean:  ## Remove build artifacts and caches
	rm -rf dist build src/chime/_version.py
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache \) -prune -exec rm -rf {} +

# ---------- releases ----------

release: release-patch  ## Cut a patch release (alias for release-patch)

release-patch:  ## Cut a patch release (0.1.0 -> 0.1.1)
	$(PY) scripts/release.py --part patch

release-minor:  ## Cut a minor release (0.1.0 -> 0.2.0)
	$(PY) scripts/release.py --part minor

release-major:  ## Cut a major release (0.1.0 -> 1.0.0)
	$(PY) scripts/release.py --part major

release-dry:  ## Dry-run a patch release (preview only)
	$(PY) scripts/release.py --part patch --dry-run

brew-bump:  ## Manually trigger the homebrew-tap bump workflow
	gh workflow run bump-chime.yml --repo MaVericKWareZ/homebrew-tap
