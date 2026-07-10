"""Watch: observe a source and fire when a predicate matches its content.

`chime watch "<command>"` re-runs a snapshot command every `--interval` and
fires a **Watch** when its output matches a predicate — the trigger is a content
predicate, never process exit (contrast `chime.run`). This slice implements the
**Poll source** only: level-state, sampled every interval, one-shot. It produces
a **Watch result** and delivers via `alerts.deliver()`, rendering its own plain
line first, per ADR-0004/0005.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from chime.parsers import fmt_duration


@dataclass(frozen=True)
class WatchResult:
    """How a Watch ended (the Watch result value), sibling of CompletionResult."""

    source: str
    predicate: str
    outcome: str  # "matched" this slice ("timed_out" → 06, "aborted" → 08)
    polls: int
    elapsed: float


def matches(text: str, predicate: str) -> bool:
    """Whether `predicate` fires against `text`.

    This slice: a case-sensitive substring over the whole snapshot output.
    Slice 06 widens this with `--regex` / `--ignore-case`.
    """
    return predicate in text


def render_line(result: WatchResult) -> str:
    """The plain default watch line (ADR-0004: one line, no banner).

    Connotation-neutral: `matched` means only that the predicate fired — chime
    does not judge the matched text as good or bad (that's the user's meaning).
    """
    duration = fmt_duration(result.elapsed)
    return f"🔔  `{result.source}` matched `{result.predicate}` ({duration})"


def _snapshot(command: str) -> str:
    """Run the snapshot command once and return its combined stdout+stderr.

    `shell=True`: `command` is the shell command string the user quoted, so
    pipes/redirects behave as typed (`kubectl get pods | grep …`).
    """
    p = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
    return p.stdout + p.stderr


def poll(
    command: str,
    predicate: str,
    *,
    interval: float,
    snapshot: Callable[[str], str] = _snapshot,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> WatchResult:
    """Sample `command` every `interval` until `predicate` matches, then fire once.

    A **Poll source** is level-state and one-shot in v1: re-run the snapshot,
    match its whole output, and return a `matched` Watch result on the first
    hit. `snapshot`/`sleep`/`clock` are injectable so tests drive the loop with
    no real waits (never-kill still holds — a poll source spawns nothing lasting).
    """
    start = clock()
    polls = 0
    while True:
        polls += 1
        if matches(snapshot(command), predicate):
            return WatchResult(command, predicate, "matched", polls, clock() - start)
        sleep(interval)
