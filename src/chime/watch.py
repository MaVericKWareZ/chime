"""Watch: observe a source and fire when a predicate matches its content.

`chime watch "<command>"` re-runs a snapshot command every `--interval` and
fires a **Watch** when its output matches a predicate — the trigger is a content
predicate, never process exit (contrast `chime.run`). This slice implements the
**Poll source** only: level-state, sampled every interval, one-shot. It produces
a **Watch result** and delivers via `alerts.deliver()`, rendering its own plain
line first, per ADR-0004/0005.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO

from chime.parsers import fmt_duration


@dataclass(frozen=True)
class WatchResult:
    """How a Watch ended (the Watch result value), sibling of CompletionResult."""

    source: str
    predicate: str
    # Content dimension: "matched" | "timed_out" (poll/file terminal; fired inline
    # for a stream). Stream lifecycle terminal: "ended" (the child exited on its
    # own — sibling of run.CompletionResult's "ended") | "aborted" (Ctrl-C).
    outcome: str
    polls: int
    elapsed: float
    returncode: int | None = None  # a --stream child's own exit code (else None)


def matches(text: str, predicate: str, *, regex: bool = False, ignore_case: bool = False) -> bool:
    """Whether `predicate` fires against `text`.

    Default: a case-sensitive substring over the whole snapshot output. `regex`
    opts into an `re.search` pattern (`ERROR|FATAL`); `ignore_case` folds case
    for both the substring and the regex form. New knobs are keyword-only so the
    poll loop's positional call stays untouched.
    """
    if regex:
        flags = re.IGNORECASE if ignore_case else 0
        return re.search(predicate, text, flags) is not None
    if ignore_case:
        return predicate.casefold() in text.casefold()
    return predicate in text


def should_reopen(prev: os.stat_result, new: os.stat_result) -> bool:
    """Whether a followed file must be re-opened and re-read from its top.

    Pure decision over two stats of the same path. A file is "the same file to
    keep tailing" only while it grows in place; re-open when:

    - **truncated** — `st_size` shrank (the producer rewound / `> file`), or
    - **rotated** — `(st_ino, st_dev)` changed (a new inode took the name, e.g.
      logrotate's rename-and-recreate).

    `st_ino` is best-effort on Windows (0 for some handles), so rotation
    detection there degrades to the truncation signal.
    """
    if new.st_size < prev.st_size:
        return True
    return (new.st_ino, new.st_dev) != (prev.st_ino, prev.st_dev)


def render_line(result: WatchResult) -> str:
    """The plain default watch line (ADR-0004: one line, no banner).

    Connotation-neutral: `matched` means only that the predicate fired — chime
    does not judge the matched text as good or bad (that's the user's meaning).
    A `timed_out` is the give-up path: the predicate never appeared in time.
    """
    duration = fmt_duration(result.elapsed)
    if result.outcome == "timed_out":
        return f"🔔  `{result.source}` timed out after {duration} — no `{result.predicate}`"
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
    regex: bool = False,
    ignore_case: bool = False,
    timeout: float | None = None,
    snapshot: Callable[[str], str] = _snapshot,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> WatchResult:
    """Sample `command` every `interval` until `predicate` matches, then fire once.

    A **Poll source** is level-state and one-shot in v1: re-run the snapshot,
    match its whole output, and return a `matched` Watch result on the first
    hit. `timeout` (default none) is the give-up path — once the elapsed time
    reaches it with no match, return a `timed_out` result instead (the CLI turns
    that into exit 1). `snapshot`/`sleep`/`clock` are injectable so tests drive
    the loop with no real waits (never-kill still holds — a poll source spawns
    nothing lasting).
    """
    start = clock()
    polls = 0
    while True:
        polls += 1
        if matches(snapshot(command), predicate, regex=regex, ignore_case=ignore_case):
            return WatchResult(command, predicate, "matched", polls, clock() - start)
        if timeout is not None and clock() - start >= timeout:
            return WatchResult(command, predicate, "timed_out", polls, clock() - start)
        sleep(interval)


def tail_file(
    path: str,
    predicate: str,
    *,
    interval: float,
    regex: bool = False,
    ignore_case: bool = False,
    timeout: float | None = None,
    keep_watching: bool = False,
    on_fire: Callable[[WatchResult], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> WatchResult:
    """Tail `path` and fire when a newly-appended line matches `predicate`.

    A **Stream source** (ADR-0005): edge-triggered, matching each *new* complete
    line once. Only content appended after the watch starts counts — the reader
    seeks to EOF on an already-present file. One-shot by default (fire once, then
    return `matched` — a file has nothing to protect, so the CLI exits). A
    trailing line with no newline is held until its newline arrives.

    `sleep`/`clock` are injectable so tests drive tailing step-wise off a real
    temp file with no real waits, mirroring `poll`.
    """
    start = clock()
    cycles = 0
    existed_at_start = os.path.exists(path)
    while not os.path.exists(path):
        # Wait-if-absent: poll for the file's creation at the --interval cadence.
        if timeout is not None and clock() - start >= timeout:
            return WatchResult(path, predicate, "timed_out", cycles, clock() - start)
        sleep(interval)
    # The tailer deliberately swaps handles across rotation, so a single `with` can't
    # span the read loop; the try/finally below closes whichever handle is live.
    f = open(path, encoding="utf-8", errors="replace")  # noqa: SIM115
    try:
        if existed_at_start:
            f.seek(0, os.SEEK_END)  # present at start → only later appends count
        # Created after we started waiting → read it from the top (position 0).
        prev_stat = os.stat(path)
        buffer = ""
        while True:
            cycles += 1
            data = f.read()
            buffer += data
            lines = buffer.split("\n")
            buffer = lines[-1]  # trailing partial line (no newline yet) stays buffered
            for line in lines[:-1]:
                if matches(line, predicate, regex=regex, ignore_case=ignore_case):
                    hit = WatchResult(path, predicate, "matched", cycles, clock() - start)
                    if keep_watching:
                        # Continuous: deliver this line and keep tailing (a file
                        # source only stops on Ctrl-C or the give-up timeout).
                        if on_fire is not None:
                            on_fire(hit)
                    else:
                        return hit  # one-shot: fire once, then the CLI exits
            if not data:
                # At EOF: follow rotation/truncation before waiting for more content.
                try:
                    new_stat = os.stat(path)
                except FileNotFoundError:
                    new_stat = None  # a momentary rotation gap — retry next cycle
                if new_stat is not None and should_reopen(prev_stat, new_stat):
                    f.close()
                    f = open(path, encoding="utf-8", errors="replace")  # noqa: SIM115
                    prev_stat = os.stat(path)
                    buffer = ""  # drop the old inode's partial line; read the new top
                    continue  # drain the rotated-in file immediately, without sleeping
                if new_stat is not None:
                    prev_stat = new_stat
            if timeout is not None and clock() - start >= timeout:
                return WatchResult(path, predicate, "timed_out", cycles, clock() - start)
            sleep(interval)
    finally:
        f.close()


def _tee_and_match(reader: IO[str], writer: IO[str], on_line: Callable[[str], None]) -> None:
    """Pump `reader` line-by-line: re-emit each line to `writer` and hand it to `on_line`.

    The pipe form of a **Stream source**: every complete line is teed to `writer`
    verbatim (its trailing newline preserved, so passthrough is faithful) and
    flushed immediately, then passed to `on_line` with the newline stripped — the
    same text `matches()` sees for a file source. `readline` blocks until a line
    or EOF, so a mid-stream partial line waits for its newline; a final line with
    no newline (the child exited mid-line) is still teed and matched once at EOF.
    Runs on one thread per pipe — it touches no shared state itself.
    """
    for line in iter(reader.readline, ""):
        writer.write(line)
        writer.flush()
        on_line(line.rstrip("\n"))


class _StreamMatcher:
    """The shared, lock-guarded firing state behind a `--stream` watch.

    Both reader threads (one per pipe) feed lines into `on_line`, so the "armed"
    state and the `on_fire` delivery are serialized by a lock. One-shot disarms
    after the first match but the child keeps running (never-kill): matching stops
    while the orchestrator keeps teeing. `--keep-watching` never disarms. A
    `timed_out` give-up (`on_timeout`) likewise disarms and keeps teeing; once
    disarmed, a later match cannot fire.
    """

    def __init__(
        self,
        command: str,
        predicate: str,
        *,
        on_fire: Callable[[WatchResult], None],
        regex: bool = False,
        ignore_case: bool = False,
        keep_watching: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.command = command
        self.predicate = predicate
        self.on_fire = on_fire
        self.regex = regex
        self.ignore_case = ignore_case
        self.keep_watching = keep_watching
        self.clock = clock
        self.start = clock()
        self.armed = True
        self.matched_ever = False
        self._lock = threading.Lock()

    def on_line(self, text: str) -> None:
        """Match one teed line; fire (and, if one-shot, disarm) on a hit."""
        with self._lock:
            if not self.armed:
                return
            if matches(text, self.predicate, regex=self.regex, ignore_case=self.ignore_case):
                self.matched_ever = True
                elapsed = self.clock() - self.start
                self.on_fire(WatchResult(self.command, self.predicate, "matched", 0, elapsed))
                if not self.keep_watching:
                    self.armed = False  # one-shot: stop matching, keep teeing

    def on_timeout(self, elapsed: float) -> None:
        """Fire the give-up alert once, then disarm — the child is never killed."""
        with self._lock:
            if not self.armed:
                return
            self.on_fire(WatchResult(self.command, self.predicate, "timed_out", 0, elapsed))
            self.armed = False


def stream(
    command: str,
    predicate: str,
    *,
    on_fire: Callable[[WatchResult], None],
    regex: bool = False,
    ignore_case: bool = False,
    timeout: float | None = None,
    keep_watching: bool = False,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    clock: Callable[[], float] = time.monotonic,
) -> WatchResult:
    """Launch `command`, tee its stdout+stderr, and fire when a line matches.

    A **command Stream source** (ADR-0005): pipe the child's stdout and stderr,
    read each with its own thread (one reader thread per pipe — uniform across
    platforms, avoiding `select`, which does not work on pipes on Windows),
    re-emit every line to chime's corresponding fd, and match each line across
    both streams. The child is **never killed** by a match or a timeout — chime
    keeps teeing until the child exits on its own (return `ended`, propagating its
    code) or the user Ctrl-Cs (return `aborted`, no alert). Content matches and
    the give-up `timed_out` fire *inline* through `on_fire`; the returned result
    carries only the lifecycle outcome and the child's exit code.

    `popen`/`stdout`/`stderr`/`clock` are injectable so tests drive the whole
    lifecycle against a fake child with pre-filled pipes — no real subprocess.
    """
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    start = clock()
    proc = popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    matcher = _StreamMatcher(
        command,
        predicate,
        on_fire=on_fire,
        regex=regex,
        ignore_case=ignore_case,
        keep_watching=keep_watching,
        clock=clock,
    )
    readers = [
        threading.Thread(
            target=_tee_and_match, args=(proc.stdout, out, matcher.on_line), daemon=True
        ),
        threading.Thread(
            target=_tee_and_match, args=(proc.stderr, err, matcher.on_line), daemon=True
        ),
    ]
    for t in readers:
        t.start()

    aborted = False
    returncode: int | None = None
    try:
        try:
            while True:
                # Only bound the wait while still matching with a live deadline; once a
                # match or the timeout has disarmed the matcher, block until the child
                # exits on its own (never-kill).
                remaining = None
                if timeout is not None and matcher.armed:
                    remaining = max(0.0, timeout - (clock() - start))
                try:
                    returncode = proc.wait(timeout=remaining)
                    break
                except subprocess.TimeoutExpired:
                    matcher.on_timeout(clock() - start)  # fire `timed_out`, keep teeing
        except KeyboardInterrupt:
            # Your Ctrl-C: the child shares the foreground process group and already
            # got the SIGINT (as in `run.run`); we only reap it. Never kill; no alert.
            aborted = True
            returncode = proc.wait()
    finally:
        for t in readers:
            t.join()  # readers have hit EOF; safe to close the pipes they drained
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
    elapsed = clock() - start
    outcome = "aborted" if aborted else "ended"
    return WatchResult(
        command, predicate, outcome, 0, elapsed, returncode=None if aborted else returncode
    )
