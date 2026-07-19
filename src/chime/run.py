"""Completion notifications: run a wrapped command and report how it ended.

`chime when <command>` runs a command as a foreground child with inherited
stdio (colors, prompts, interactivity untouched), times it, and produces a
**Completion result** describing how it ended. The alert itself is delivered by
`alerts.deliver()`; this module owns the trigger (process exit) and a plain
default rendering, per ADR-0004.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass

from chime.parsers import fmt_duration


@dataclass(frozen=True)
class CompletionResult:
    """How an observed process ended (the Completion result value)."""

    command: str
    outcome: str  # "passed" | "failed" | "aborted" ("ended" lands with monitor)
    exit_code: int | None
    elapsed: float


def outcome_for(exit_code: int, was_interrupted: bool = False) -> str:
    """Classify a Completion result by its chime-facing exit code.

    A run chime itself was asked to interrupt (your Ctrl-C) is ``aborted``
    regardless of the child's exit code — a foreign-signal death is *not*
    aborted and falls through to ``failed`` (per CONTEXT.md).
    """
    if was_interrupted:
        return "aborted"
    return "passed" if exit_code == 0 else "failed"


def should_fire(outcome: str, only: str | None) -> bool:
    """Whether a Completion notification should fire, given a firing filter.

    `--only-fail` (``only="fail"``) fires only on a `failed` completion;
    `--only-pass` (``only="pass"``) only on a `passed` one; bare `chime when`
    (``only=None``) fires on any completion. An `aborted` run (your Ctrl-C)
    never fires regardless — the exit code is still propagated by the caller.
    """
    if outcome == "aborted":
        return False
    if only is None:
        return True
    return (only == "fail" and outcome == "failed") or (only == "pass" and outcome == "passed")


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
    duration = fmt_duration(result.elapsed)
    if result.outcome == "ended":
        # Pipe form (`chime monitor`): no exit code, an optional label fills the
        # command slot. Bare stream → drop the backticked slot entirely.
        label = f"`{result.command}` " if result.command else ""
        return f"🔔  {label}stream ended ({duration})"
    detail = _completion_detail(result.exit_code)
    return f"🔔  `{result.command}` {detail} ({duration})"


def _completion_detail(exit_code: int | None) -> str:
    """Render the middle of the completion line, naming a signal death.

    A signal death normalizes to ``128 + signum``; on POSIX we recover the
    signal name, degrading to an abnormal-exit string on Windows (which has no
    POSIX signal set) or for an unrecognized signum.
    """
    if exit_code is not None and 128 < exit_code < 192:
        if sys.platform != "win32":
            try:
                name = signal.Signals(exit_code - 128).name
                return f"killed by {name}"
            except ValueError:
                pass
        return f"exited abnormally (code {exit_code})"
    return f"finished — exit {exit_code}"


def run(argv: list[str]) -> CompletionResult:
    """Run `argv` as a foreground child, timing it, and report how it ended.

    Stdio is inherited (not captured), so the child's colors, progress bars and
    interactive prompts behave exactly as if it were unwrapped. Chime never
    kills the child (ADR-0005); it waits for the process to exit on its own.

    The firing decision (`--only-fail`/`--only-pass`) lives in the CLI, which
    consults `should_fire` once this result is known — `run` only observes.
    """
    command = " ".join(argv)
    start = time.monotonic()
    was_interrupted = False
    try:
        completed = subprocess.run(argv, check=False)
    except FileNotFoundError:
        exit_code = 127
    except PermissionError:
        exit_code = 126
    except KeyboardInterrupt:
        # Chime's own caught interrupt: the child, sharing the console/process
        # group, already received the SIGINT and has been reaped. This is an
        # `aborted` run (never-kill still holds; we only wait) → exit 130.
        was_interrupted = True
        exit_code = exit_status(-signal.SIGINT)
    else:
        exit_code = exit_status(completed.returncode)
    elapsed = time.monotonic() - start
    return CompletionResult(command, outcome_for(exit_code, was_interrupted), exit_code, elapsed)


def monitor(stdin_buf, stdout_buf, label: str) -> CompletionResult:
    """Tee `stdin_buf`→`stdout_buf` byte-faithfully, firing when the pipe closes.

    The pipe form of a Completion notification (`producer | chime monitor`):
    the producer's bytes pass through untouched — binary and colored output are
    copied in fixed-size chunks (never text-mode, never line-buffered) — and the
    trigger is EOF (the producer exited). A pipe carries no exit status, so the
    outcome is `ended` with `exit_code` absent; the optional `label` fills the
    command slot for display. Timed from this call, mirroring `run`.
    """
    start = time.monotonic()
    read = getattr(stdin_buf, "read1", stdin_buf.read)
    try:
        while chunk := read(65536):
            stdout_buf.write(chunk)
            stdout_buf.flush()
    except BrokenPipeError:
        # The downstream reader closed early (mid-pipe SIGPIPE). Redirect our
        # stdout fd to the null device so CPython's shutdown flush is quiet, then
        # re-raise as the distinct downstream-close signal; `cmd_monitor` maps it
        # to a quiet exit 141 (no `ended` completion — the producer never EOF'd).
        _silence_broken_pipe(stdout_buf)
        raise
    elapsed = time.monotonic() - start
    return CompletionResult(label, "ended", None, elapsed)


def _silence_broken_pipe(buf) -> None:
    """Point `buf`'s fd at the null device so the interpreter's shutdown flush is quiet.

    A no-op when `buf` has no real fd (a fake buffer in tests) — the caller still
    re-raises `BrokenPipeError` to signal the downstream close.
    """
    try:
        fd = buf.fileno()
    except (AttributeError, OSError, ValueError):
        return
    os.dup2(os.open(os.devnull, os.O_WRONLY), fd)
