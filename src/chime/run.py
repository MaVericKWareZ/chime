"""Completion notifications: run a wrapped command and report how it ended.

`chime when <command>` runs a command as a foreground child with inherited
stdio (colors, prompts, interactivity untouched), times it, and produces a
**Completion result** describing how it ended. The alert itself is delivered by
`alerts.deliver()`; this module owns the trigger (process exit) and a plain
default rendering, per ADR-0004.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

from chime.parsers import fmt_duration


@dataclass(frozen=True)
class CompletionResult:
    """How an observed process ended (the Completion result value)."""

    command: str
    outcome: str  # "passed" | "failed" (this slice; "aborted"/"ended" land later)
    exit_code: int | None
    elapsed: float


def outcome_for(exit_code: int) -> str:
    """Classify a Completion result by its chime-facing exit code."""
    return "passed" if exit_code == 0 else "failed"


def exit_status(returncode: int) -> int:
    """Map a subprocess return code to chime's own exit status.

    Normal codes propagate unchanged; a negative return code is signal death
    (`-signum`), which becomes the shell convention `128 + signum`.
    """
    return 128 + (-returncode) if returncode < 0 else returncode


def split_argv(
    raw: list[str], *, bool_flags: set[str], value_flags: set[str]
) -> tuple[list[str], list[str]]:
    """Model-A split of `chime when` argv into (chime opts, wrapped command).

    Chime's own options are consumed up to the first bare token; that token and
    everything after it is the opaque wrapped command. ``--`` is an explicit
    escape (its remainder is the command). An unknown ``--flag`` before the
    first bare token raises ``ValueError`` — that's what ``--`` is for.
    """
    opts: list[str] = []
    i = 0
    while i < len(raw):
        tok = raw[i]
        if tok == "--":
            return opts, raw[i + 1 :]
        if tok in bool_flags:
            opts.append(tok)
            i += 1
        elif tok in value_flags:
            if i + 1 >= len(raw):
                raise ValueError(f"{tok} needs a value")
            opts.extend([tok, raw[i + 1]])
            i += 2
        elif tok.startswith("-"):
            raise ValueError(f"unknown option {tok}")
        else:
            return opts, raw[i:]
    return opts, []


def render_line(result: CompletionResult) -> str:
    """The plain default completion line (ADR-0004: one line, no banner)."""
    return (
        f"🔔  `{result.command}` finished — "
        f"exit {result.exit_code} ({fmt_duration(result.elapsed)})"
    )


def run(argv: list[str], *, only: str | None = None) -> CompletionResult:
    """Run `argv` as a foreground child, timing it, and report how it ended.

    Stdio is inherited (not captured), so the child's colors, progress bars and
    interactive prompts behave exactly as if it were unwrapped. Chime never
    kills the child (ADR-0005); it waits for the process to exit on its own.

    ``only`` is accepted for interface stability but unused until slice 03.
    """
    command = " ".join(argv)
    start = time.monotonic()
    try:
        completed = subprocess.run(argv, check=False)
    except FileNotFoundError:
        exit_code = 127
    except PermissionError:
        exit_code = 126
    else:
        exit_code = exit_status(completed.returncode)
    elapsed = time.monotonic() - start
    return CompletionResult(command, outcome_for(exit_code), exit_code, elapsed)
