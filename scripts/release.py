#!/usr/bin/env python3
"""Cut a new chime release.

Steps:
  1. Validate the version, working tree, branch, and that main CI is green.
  2. Rewrite src/chime/__init__.py with the new version.
  3. Promote CHANGELOG [Unreleased] into a dated [X.Y.Z] section and refresh
     the compare/tag link footer.
  4. Show the diff and ask for confirmation.
  5. Commit + push the bump.
  6. Wait for CI to go green on the new commit.
  7. Tag v<version> and push the tag — that triggers release.yml.
  8. (Optional) Trigger the homebrew-tap bump workflow so brew users get the
     new version without waiting for the next daily cron.

Usage:
  python scripts/release.py 0.2.0
  python scripts/release.py 0.2.0 --dry-run       # show planned edits, do nothing
  python scripts/release.py 0.2.0 --yes           # skip the confirmation prompt
  python scripts/release.py 0.2.0 --no-brew-bump  # don't ping homebrew-tap
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT_FILE = ROOT / "src" / "chime" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$")
VERSION_LINE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
DIM = "\033[2m"
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"


def c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}" if sys.stdout.isatty() else text


def die(msg: str, code: int = 1) -> None:
    print(c(f"error: {msg}", RED), file=sys.stderr)
    sys.exit(code)


def run(
    cmd: list[str], *, capture: bool = False, check: bool = True
) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, check=check, text=True, capture_output=capture)


def confirm(prompt: str) -> bool:
    try:
        return input(c(f"{prompt} [y/N] ", BOLD)).strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        return False


# ---------- preflight ----------


def current_version() -> str:
    match = VERSION_LINE.search(INIT_FILE.read_text())
    if not match:
        die(f"could not find __version__ in {INIT_FILE.relative_to(ROOT)}")
    return match.group(1)


def parse_semver(v: str) -> tuple[int, int, int]:
    base = v.split("-", 1)[0].split("+", 1)[0]
    return tuple(int(x) for x in base.split("."))  # type: ignore[return-value]


def check_clean_tree() -> None:
    status = run(["git", "status", "--porcelain"], capture=True).stdout
    if status.strip():
        die("working tree is dirty — commit or stash before releasing\n" + status)


def check_branch() -> None:
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True).stdout.strip()
    if branch != "main":
        die(f"current branch is '{branch}' — release from 'main'")


def check_main_ci_green() -> None:
    print(c("checking CI status on main…", DIM))
    res = run(
        [
            "gh",
            "run",
            "list",
            "--workflow=ci.yml",
            "--branch=main",
            "--limit=1",
            "--json",
            "conclusion,status,headSha",
        ],
        capture=True,
        check=False,
    )
    if res.returncode != 0:
        die("could not query CI status via gh — is gh CLI authed?")
    runs = json.loads(res.stdout)
    if not runs:
        die("no CI runs found on main")
    r = runs[0]
    if r["status"] != "completed":
        die(f"latest CI run on main is still {r['status']} — wait for it before releasing")
    if r["conclusion"] != "success":
        die(f"latest CI run on main concluded as {r['conclusion']} — fix it before releasing")


# ---------- file edits ----------


def rewrite_version_file(new_version: str) -> str:
    text = INIT_FILE.read_text()
    new_text, n = VERSION_LINE.subn(f'__version__ = "{new_version}"', text, count=1)
    if n != 1:
        die("failed to rewrite __version__ line")
    return new_text


def rewrite_changelog(new_version: str, today: str, prev: str) -> str:
    text = CHANGELOG.read_text()

    # 1. Promote the [Unreleased] section header to dated [new_version].
    # Use [ \t]* (not \s*) so the trailing-whitespace match doesn't eat the
    # blank line that separates the heading from the section body.
    pattern = r"^## \[Unreleased\][ \t]*$"
    if not re.search(pattern, text, re.MULTILINE):
        die("CHANGELOG.md is missing the `## [Unreleased]` heading")
    text = re.sub(
        pattern,
        f"## [Unreleased]\n\n## [{new_version}] - {today}",
        text,
        count=1,
        flags=re.MULTILINE,
    )

    # 2. Update the link footer.
    unreleased_link = re.compile(r"^\[Unreleased\]:\s*(.+)$", re.MULTILINE)
    m = unreleased_link.search(text)
    if not m:
        die("CHANGELOG.md is missing the `[Unreleased]: ...` link line")
    old_link = m.group(1)
    new_unreleased = re.sub(
        rf"compare/v{re.escape(prev)}\.\.\.HEAD", f"compare/v{new_version}...HEAD", old_link
    )
    new_compare = re.sub(
        rf"compare/v{re.escape(prev)}\.\.\.HEAD", f"compare/v{prev}...v{new_version}", old_link
    )
    if new_unreleased == old_link:
        # The format didn't match what we expected. Bail loudly.
        die(f"unexpected [Unreleased] link format; refusing to edit blindly:\n  {old_link}")
    text = unreleased_link.sub(f"[Unreleased]: {new_unreleased}", text, count=1)
    insertion = f"[Unreleased]: {new_unreleased}\n[{new_version}]: {new_compare}"
    text = text.replace(f"[Unreleased]: {new_unreleased}", insertion, 1)
    return text


# ---------- ci-wait + tag ----------


def wait_for_main_ci(commit_sha: str, *, timeout_s: int = 1200, poll_s: int = 15) -> None:
    print(c(f"waiting for CI on {commit_sha[:8]}… (up to {timeout_s // 60} min)", DIM))
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        res = run(
            [
                "gh",
                "run",
                "list",
                "--workflow=ci.yml",
                "--branch=main",
                "--limit=5",
                "--json",
                "conclusion,status,headSha,databaseId",
            ],
            capture=True,
            check=False,
        )
        if res.returncode != 0:
            print(c("  gh query failed, retrying…", YELLOW))
            time.sleep(poll_s)
            continue
        runs = [r for r in json.loads(res.stdout) if r["headSha"] == commit_sha]
        if not runs:
            print(c("  no run yet for this commit, waiting…", DIM))
            time.sleep(poll_s)
            continue
        r = runs[0]
        if r["status"] != "completed":
            print(c(f"  status={r['status']} — checking again in {poll_s}s", DIM))
            time.sleep(poll_s)
            continue
        if r["conclusion"] == "success":
            print(c("  ✓ CI green", GREEN))
            return
        die(f"CI on {commit_sha[:8]} concluded as {r['conclusion']} — fix and retry")
    die(f"timed out after {timeout_s}s waiting for CI")


# ---------- main ----------


def main() -> None:
    p = argparse.ArgumentParser(
        prog="release", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("version", help="new version, e.g. 0.2.0")
    p.add_argument(
        "--dry-run", action="store_true", help="show planned edits, don't write or push anything"
    )
    p.add_argument("--yes", action="store_true", help="skip confirmation prompt")
    p.add_argument(
        "--no-brew-bump", action="store_true", help="don't trigger the homebrew-tap bump workflow"
    )
    p.add_argument(
        "--no-ci-wait",
        action="store_true",
        help="don't wait for main CI to pass before tagging (NOT recommended)",
    )
    args = p.parse_args()

    new_version = args.version.lstrip("v")
    if not SEMVER.match(new_version):
        die(f"'{new_version}' is not a valid semver (e.g. 0.2.0)")

    current = current_version()
    if parse_semver(new_version) <= parse_semver(current):
        die(f"new version {new_version} is not greater than current {current}")

    print(c(f"chime release: {current} → {new_version}", BOLD + CYAN))
    print()

    if not args.dry_run:
        check_clean_tree()
        check_branch()
        check_main_ci_green()

    new_init = rewrite_version_file(new_version)
    new_changelog = rewrite_changelog(new_version, date.today().isoformat(), current)

    print(c("planned edits:", BOLD))
    print(c(f"  - {INIT_FILE.relative_to(ROOT)}: __version__ → {new_version}", DIM))
    print(
        c(
            f"  - {CHANGELOG.relative_to(ROOT)}: promote [Unreleased] → [{new_version}], add new [Unreleased]",
            DIM,
        )
    )
    print()

    if args.dry_run:
        print(c("dry-run — no files written", YELLOW))
        return

    if not args.yes and not confirm(f"proceed with release of v{new_version}?"):
        print(c("aborted", YELLOW))
        sys.exit(0)

    INIT_FILE.write_text(new_init)
    CHANGELOG.write_text(new_changelog)

    print(c("committing…", DIM))
    run(["git", "add", str(INIT_FILE), str(CHANGELOG)])
    run(["git", "commit", "-m", f"chore: release v{new_version}"])
    commit_sha = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()

    print(c("pushing main…", DIM))
    run(["git", "push", "origin", "main"])

    if not args.no_ci_wait:
        wait_for_main_ci(commit_sha)

    tag = f"v{new_version}"
    print(c(f"tagging {tag}…", DIM))
    run(["git", "tag", tag])
    run(["git", "push", "origin", tag])

    print()
    print(c(f"✅ {tag} released", BOLD + GREEN))
    print(
        c("  release workflow:", DIM)
        + " https://github.com/MaVericKWareZ/chime/actions/workflows/release.yml"
    )
    print(c("  PyPI (in ~2 min):", DIM) + f" https://pypi.org/project/chime-cli/{new_version}/")

    if not args.no_brew_bump:
        print()
        print(c("triggering homebrew-tap bump workflow…", DIM))
        res = run(
            ["gh", "workflow", "run", "bump-chime.yml", "--repo", "MaVericKWareZ/homebrew-tap"],
            check=False,
            capture=True,
        )
        if res.returncode == 0:
            print(
                c("  ✓ brew bump queued", GREEN)
                + c(" — https://github.com/MaVericKWareZ/homebrew-tap/actions", DIM)
            )
        else:
            print(c("  ! couldn't trigger brew bump — daily cron will catch it within 24h", YELLOW))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(130)
