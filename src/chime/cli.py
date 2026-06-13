"""Command-line interface for chime."""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from chime import __version__, alerts, state
from chime.parsers import fmt_clock, fmt_duration, parse_duration, parse_time
from chime.term import BOLD, CYAN, DIM, GREEN, MAGENTA, RED, YELLOW, c

USAGE = """chime — friendly terminal alarms, timers & pomodoro

Usage:
  chime <duration> [message]       Timer (e.g., 10m, 1h30m, 90s, 0.5h)
  chime at <time> [message]        Alarm at clock time (15:30, 3:30pm, 9am)
  chime pomodoro [work] [brk] [rounds]
                                   Pomodoro cycles (default 25 5 4)
  chime stopwatch                  Count-up timer
  chime list                       List background alarms
  chime cancel <id|all>            Cancel a background alarm
  chime sounds [name]              List/preview alarm sounds
  chime version                    Print version
  chime help                       Show this help

Options:
  --bg                             Run alarm in background, return immediately
  --sound NAME                     Alert sound (default: Glass)
  --repeat N                       Repeat sound N times (default: 3)
  --say                            Speak the message aloud
  --no-sound                       Silent — notification only

Examples:
  chime 10m "tea is ready"
  chime 1h30m
  chime at 9:30am standup
  chime --bg 25m focus
  chime pomodoro
  chime pomodoro 50 10 3
  chime list
"""

SUBCOMMANDS = {
    "at",
    "pomodoro",
    "pom",
    "stopwatch",
    "sw",
    "list",
    "ls",
    "cancel",
    "sounds",
    "version",
    "_bg-runner",  # internal: invoked by spawned background process on Windows
}
BOOL_FLAGS = {"--bg", "--say", "--no-sound"}
VALUE_FLAGS = {"--sound", "--repeat"}


# ---------- countdown + run ----------


def countdown(seconds: float, label: str | None = None) -> bool:
    """Live countdown. Returns True if completed, False if cancelled."""
    end = time.time() + seconds
    target_str = datetime.fromtimestamp(end).strftime("%H:%M:%S")
    if label:
        print(label)
    print(c(f"  target {target_str}  ·  {fmt_duration(seconds)} from now", DIM))
    print(c("  Ctrl-C to cancel", DIM))
    print()
    try:
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                sys.stdout.write(f"\r  {c('00:00', GREEN)}                    \n")
                return True
            sys.stdout.write(f"\r  {c(fmt_clock(remaining), BOLD + CYAN)}      ")
            sys.stdout.flush()
            frac = remaining - int(remaining)
            time.sleep(max(0.05, frac if frac > 0 else 0.25))
    except KeyboardInterrupt:
        sys.stdout.write("\r")
        print(c("  cancelled", RED) + "                    ")
        return False


def run_background(
    seconds: float,
    message: str | None,
    sound: str,
    repeat: int,
    do_say: bool,
    silent: bool,
) -> None:
    """Spawn a detached background process that sleeps and fires the alarm.

    POSIX: double-style fork + setsid.
    Windows: subprocess.Popen with DETACHED_PROCESS, re-invoking chime with
             the internal `_bg-runner` subcommand.
    """
    if sys.platform == "win32":
        _run_background_windows(seconds, message, sound, repeat, do_say, silent)
        return
    pid = os.fork()
    if pid > 0:
        _register_bg(pid, seconds, message, sound, silent)
        return
    os.setsid()
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    try:
        time.sleep(max(0, seconds))
        alerts.trigger(message, sound, repeat, do_say, silent)
    finally:
        try:
            state.remove(os.getpid())
        finally:
            os._exit(0)


def _run_background_windows(
    seconds: float,
    message: str | None,
    sound: str,
    repeat: int,
    do_say: bool,
    silent: bool,
) -> None:
    payload = json.dumps(
        {
            "seconds": seconds,
            "message": message or "",
            "sound": sound,
            "repeat": repeat,
            "say": do_say,
            "silent": silent,
        }
    )
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    proc = subprocess.Popen(
        [sys.executable, "-m", "chime", "_bg-runner", encoded],
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    _register_bg(proc.pid, seconds, message, sound, silent)


def _register_bg(pid: int, seconds: float, message: str | None, sound: str, silent: bool) -> None:
    target = datetime.now() + timedelta(seconds=seconds)
    state.add(
        {
            "pid": pid,
            "message": message or "",
            "target": target.isoformat(timespec="seconds"),
            "started": datetime.now().isoformat(timespec="seconds"),
            "sound": sound,
            "silent": silent,
        }
    )
    print(
        c(f"⏰  alarm set for {target.strftime('%H:%M:%S')}", GREEN)
        + c(f"  (id {pid}, in {fmt_duration(seconds)})", DIM)
    )
    if message:
        print(c(f"    message: {message}", DIM))
    print(c(f"    cancel:  chime cancel {pid}", DIM))


def run_alarm(
    seconds: float, message: str | None, opts: Any, target_dt: datetime | None = None
) -> None:
    if seconds <= 0:
        print(c("error: target time is in the past", RED))
        sys.exit(2)
    sound = opts.sound or alerts.DEFAULT_SOUND
    if opts.bg:
        run_background(seconds, message, sound, opts.repeat, opts.say, opts.no_sound)
        return
    title = message if message else "timer"
    label = c(f"⏳  {title}", BOLD + CYAN)
    if target_dt is not None:
        label += c(f"  @ {target_dt.strftime('%H:%M')}", DIM)
    if countdown(seconds, label=label):
        alerts.trigger(message, sound, opts.repeat, opts.say, opts.no_sound)


# ---------- subcommand handlers ----------


def cmd_at(args: argparse.Namespace) -> None:
    try:
        target = parse_time(args.time)
    except ValueError as e:
        print(c(f"error: {e}", RED))
        sys.exit(2)
    seconds = (target - datetime.now()).total_seconds()
    message = " ".join(args.message) if args.message else None
    run_alarm(seconds, message, args, target_dt=target)


def cmd_pomodoro(args: argparse.Namespace) -> None:
    work = float(args.work) if args.work else 25.0
    brk = float(args.brk) if args.brk else 5.0
    rounds = int(args.rounds) if args.rounds else 4
    if work <= 0 or brk <= 0 or rounds <= 0:
        print(c("error: pomodoro values must be positive", RED))
        sys.exit(2)
    sound = args.sound or alerts.DEFAULT_SOUND
    print(
        c("🍅 pomodoro", BOLD + MAGENTA) + c(f"  {work:g}m work / {brk:g}m break × {rounds}", DIM)
    )
    print()
    for i in range(1, rounds + 1):
        title = c(f"round {i}/{rounds}", BOLD)
        if not countdown(work * 60, label=c(f"🔨  {title}  work", CYAN)):
            print(c("pomodoro stopped", YELLOW))
            return
        alerts.notify(f"Pomodoro {i}/{rounds}", "Work done — take a break!", sound=sound)
        alerts.play_sound(sound, repeat=2)
        print()
        if i == rounds:
            print(c(f"✅  {rounds} rounds done — great work!", GREEN))
            return
        if not countdown(brk * 60, label=c(f"☕  {title}  break", GREEN)):
            print(c("pomodoro stopped", YELLOW))
            return
        alerts.notify(f"Pomodoro {i}/{rounds}", "Break over — back to work!", sound=sound)
        alerts.play_sound(sound, repeat=2)
        print()


def cmd_stopwatch(args: argparse.Namespace) -> None:
    print(c("⏱   stopwatch", BOLD + CYAN) + c("  Ctrl-C to stop", DIM))
    print()
    start = time.time()
    try:
        while True:
            elapsed = time.time() - start
            sys.stdout.write(f"\r  {c(fmt_clock(elapsed), BOLD + CYAN)}     ")
            sys.stdout.flush()
            time.sleep(0.1)
    except KeyboardInterrupt:
        elapsed = time.time() - start
        sys.stdout.write("\r")
        print(c(f"  elapsed: {fmt_clock(elapsed)}", GREEN) + "      ")


def cmd_list(args: argparse.Namespace) -> None:
    alarms = state.prune()
    if not alarms:
        print(c("no background alarms", DIM))
        return
    print(c(f"{len(alarms)} background alarm(s):", BOLD))
    now = datetime.now()
    for a in alarms:
        target = datetime.fromisoformat(a["target"])
        remaining = (target - now).total_seconds()
        rem = fmt_duration(remaining) if remaining > 0 else "ringing"
        msg = a["message"] or c("(no message)", DIM)
        print(
            f"  {c(str(a['pid']).rjust(6), CYAN)}  "
            f"{c(target.strftime('%a %H:%M:%S'), BOLD)}  "
            f"in {c(rem, YELLOW)}  — {msg}"
        )


def cmd_cancel(args: argparse.Namespace) -> None:
    alarms = state.prune()
    if not alarms:
        print(c("no background alarms to cancel", DIM))
        return
    if args.id == "all":
        for a in alarms:
            with contextlib.suppress(OSError):
                os.kill(a["pid"], signal.SIGTERM)
        state.save([])
        print(c(f"cancelled {len(alarms)} alarm(s)", GREEN))
        return
    try:
        pid = int(args.id)
    except ValueError:
        print(c("error: id must be a number or 'all'", RED))
        sys.exit(2)
    if not any(a["pid"] == pid for a in alarms):
        print(c(f"no alarm with id {pid}", RED))
        sys.exit(1)
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGTERM)
    state.remove(pid)
    print(c(f"cancelled alarm {pid}", GREEN))


def cmd_sounds(args: argparse.Namespace) -> None:
    sounds = alerts.list_sounds()
    if not sounds:
        print(c("no system sounds available on this platform", DIM))
        return
    if args.preview:
        if args.preview not in sounds:
            print(c(f"unknown sound '{args.preview}'", RED))
            sys.exit(1)
        print(c(f"playing {args.preview}…", DIM))
        alerts.play_sound(args.preview, repeat=1)
        return
    print(c("available sounds:", BOLD))
    for s in sounds:
        marker = c("  (default)", DIM) if s == alerts.DEFAULT_SOUND else ""
        print(f"  {c(s, CYAN)}{marker}")
    print(c("\npreview: chime sounds <name>", DIM))


def cmd_version(args: argparse.Namespace) -> None:
    print(f"chime {__version__}")


def cmd_bg_runner(args: argparse.Namespace) -> None:
    """Internal: invoked by the Windows background spawn. Not user-facing."""
    try:
        payload = json.loads(base64.b64decode(args.payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        sys.exit(0)
    try:
        time.sleep(max(0, float(payload.get("seconds", 0))))
        alerts.trigger(
            payload.get("message") or None,
            payload.get("sound") or alerts.DEFAULT_SOUND,
            int(payload.get("repeat", 3)),
            bool(payload.get("say", False)),
            bool(payload.get("silent", False)),
        )
    finally:
        with contextlib.suppress(Exception):
            state.remove(os.getpid())


# ---------- argparse + dispatch ----------


def _add_alarm_opts(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--bg", action="store_true", help="run in background")
    sp.add_argument("--sound", help=f"alert sound (default: {alerts.DEFAULT_SOUND})")
    sp.add_argument("--repeat", type=int, default=3, help="repeat sound N times")
    sp.add_argument("--say", action="store_true", help="speak the message aloud")
    sp.add_argument("--no-sound", action="store_true", help="silent — notification only")


def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="chime", add_help=False)
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("at", add_help=False)
    sp.add_argument("time")
    sp.add_argument("message", nargs="*")
    _add_alarm_opts(sp)
    sp.set_defaults(func=cmd_at)

    sp = sub.add_parser("pomodoro", aliases=["pom"], add_help=False)
    sp.add_argument("work", nargs="?")
    sp.add_argument("brk", nargs="?")
    sp.add_argument("rounds", nargs="?")
    _add_alarm_opts(sp)
    sp.set_defaults(func=cmd_pomodoro)

    sp = sub.add_parser("stopwatch", aliases=["sw"], add_help=False)
    sp.set_defaults(func=cmd_stopwatch)

    sp = sub.add_parser("list", aliases=["ls"], add_help=False)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("cancel", add_help=False)
    sp.add_argument("id")
    sp.set_defaults(func=cmd_cancel)

    sp = sub.add_parser("sounds", add_help=False)
    sp.add_argument("preview", nargs="?")
    sp.set_defaults(func=cmd_sounds)

    sp = sub.add_parser("version", add_help=False)
    sp.set_defaults(func=cmd_version)

    # Internal — invoked by the Windows background spawn. Not documented.
    sp = sub.add_parser("_bg-runner", add_help=False)
    sp.add_argument("payload")
    sp.set_defaults(func=cmd_bg_runner)

    return p


def _split_flags(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split argv into (positional, flags) — flags can appear anywhere."""
    pos: list[str] = []
    flags: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in BOOL_FLAGS:
            flags.append(a)
            i += 1
        elif a in VALUE_FLAGS:
            if i + 1 >= len(argv):
                print(c(f"error: {a} needs a value", RED))
                sys.exit(2)
            flags.extend([a, argv[i + 1]])
            i += 2
        else:
            pos.append(a)
            i += 1
    return pos, flags


def _bare_duration(positional: list[str], flags: list[str]) -> None:
    duration = positional[0]
    try:
        seconds = parse_duration(duration)
    except ValueError:
        print(c(f"error: '{duration}' is not a known command or duration", RED))
        print(c("       try: chime help", DIM))
        sys.exit(2)
    ns = argparse.Namespace(
        bg="--bg" in flags,
        say="--say" in flags,
        no_sound="--no-sound" in flags,
        sound=None,
        repeat=3,
    )
    if "--sound" in flags:
        ns.sound = flags[flags.index("--sound") + 1]
    if "--repeat" in flags:
        try:
            ns.repeat = int(flags[flags.index("--repeat") + 1])
        except ValueError:
            print(c("error: --repeat needs a number", RED))
            sys.exit(2)
    message = " ".join(positional[1:]) if len(positional) > 1 else None
    run_alarm(seconds, message, ns)


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if not args or any(a in ("help", "-h", "--help") for a in args):
        print(USAGE)
        return
    if any(a in ("-V", "--version") for a in args):
        print(f"chime {__version__}")
        return
    positional, flags = _split_flags(args)
    leftover = [a for a in positional if a.startswith("--")]
    if leftover:
        print(c(f"error: unknown option {leftover[0]}", RED))
        sys.exit(2)
    if positional and positional[0] in SUBCOMMANDS:
        parser = _make_parser()
        ns = parser.parse_args([positional[0], *positional[1:], *flags])
        if not hasattr(ns, "func"):
            print(USAGE)
            return
        ns.func(ns)
        return
    if not positional:
        print(c("error: nothing to do — try: chime help", RED))
        sys.exit(2)
    _bare_duration(positional, flags)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(130)
