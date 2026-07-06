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
from zoneinfo import ZoneInfo

from chime import __version__, alerts, config, state, tz
from chime.parsers import fmt_clock, fmt_duration, parse_duration, parse_time
from chime.term import BOLD, CYAN, DIM, GREEN, MAGENTA, RED, YELLOW, c

USAGE = """chime — friendly terminal alarms, timers & pomodoro

Usage:
  chime <duration> [message]       Timer (e.g., 10m, 1h30m, 90s, 0.5h)
  chime at <time> [message]        Alarm at clock time (15:30, 3:30pm, 9am)
                                   Time may carry a timezone: at "9am EDT"
  chime pomodoro [work] [brk] [rounds]
                                   Pomodoro cycles (default 25 5 4)
  chime stopwatch                  Count-up timer
  chime list                       List background alarms
  chime cancel <id|all>            Cancel a background alarm
  chime sounds [name]              List/preview alarm sounds
  chime config [key]               Show config (or one key's value)
  chime config set <key> <value>   Set a config value (e.g. timezone)
  chime config get <key>           Print one value (script-friendly)
  chime config unset <key>         Clear one key
  chime config reset               Wipe the whole config
  chime version                    Print version
  chime help                       Show this help

Options:
  --bg                             Run alarm in background, return immediately
  --sound NAME                     Alert sound (default: Glass)
  --repeat N                       Repeat sound N times (default: 3)
  --tz ZONE                        Source timezone for the alarm (e.g. EDT,
                                   Asia/Kolkata); can't combine with inline tz
  --say                            Speak the message aloud
  --no-sound                       Silent — notification only

Timezones:
  Alarms accept a source timezone inline ("9am EDT") or via --tz. Unambiguous
  abbreviations and full IANA names work; ambiguous ones (IST, CST, BST, AST)
  error with candidates. Set a default with: chime config set timezone <zone>.
  See the README's Timezones section for the full policy.

Examples:
  chime 10m "tea is ready"
  chime 1h30m
  chime at 9:30am standup
  chime at "9am EDT" standup
  chime at 9am --tz Asia/Kolkata
  chime config set timezone Asia/Kolkata
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
    "config",
    "version",
    "_bg-runner",  # internal: invoked by spawned background process on Windows
}
BOOL_FLAGS = {"--bg", "--say", "--no-sound"}
VALUE_FLAGS = {"--sound", "--repeat", "--tz"}


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
    *,
    source_tz: str | None = None,
    source_label: str | None = None,
) -> None:
    """Spawn a detached background process that sleeps and fires the alarm.

    POSIX: double-style fork + setsid.
    Windows: subprocess.Popen with DETACHED_PROCESS, re-invoking chime with
             the internal `_bg-runner` subcommand.
    """
    if sys.platform == "win32":
        _run_background_windows(
            seconds,
            message,
            sound,
            repeat,
            do_say,
            silent,
            source_tz=source_tz,
            source_label=source_label,
        )
        return
    pid = os.fork()
    if pid > 0:
        _register_bg(
            pid,
            seconds,
            message,
            sound,
            silent,
            source_tz=source_tz,
            source_label=source_label,
        )
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
    *,
    source_tz: str | None = None,
    source_label: str | None = None,
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
    _register_bg(
        proc.pid,
        seconds,
        message,
        sound,
        silent,
        source_tz=source_tz,
        source_label=source_label,
    )


def _register_bg(
    pid: int,
    seconds: float,
    message: str | None,
    sound: str,
    silent: bool,
    *,
    source_tz: str | None = None,
    source_label: str | None = None,
) -> None:
    target = datetime.now(tz.system_tz()) + timedelta(seconds=seconds)
    entry = {
        "pid": pid,
        "message": message or "",
        "target": target.isoformat(timespec="seconds"),
        "started": datetime.now().isoformat(timespec="seconds"),
        "sound": sound,
        "silent": silent,
    }
    if source_tz is not None:
        entry["source_tz"] = source_tz
        entry["source_label"] = source_label
    state.add(entry)
    print(
        c(f"⏰  alarm set for {target.strftime('%H:%M:%S')}", GREEN)
        + c(f"  (id {pid}, in {fmt_duration(seconds)})", DIM)
    )
    if message:
        print(c(f"    message: {message}", DIM))
    print(c(f"    cancel:  chime cancel {pid}", DIM))


def run_alarm(
    seconds: float,
    message: str | None,
    opts: Any,
    target_dt: datetime | None = None,
    source_label: str | None = None,
    source_tz: str | None = None,
    record_label: str | None = None,
) -> None:
    # `source_label` is the foreground header label (target.tzname() at the
    # target moment); `record_label` is the user's typed token persisted to the
    # background record. They coincide for plain abbreviations but diverge for
    # IANA input or an off-season abbreviation, so they are tracked separately.
    if seconds <= 0:
        print(c("error: target time is in the past", RED))
        sys.exit(2)
    sound = opts.sound or alerts.DEFAULT_SOUND
    if opts.bg:
        run_background(
            seconds,
            message,
            sound,
            opts.repeat,
            opts.say,
            opts.no_sound,
            source_tz=source_tz,
            source_label=record_label,
        )
        return
    title = message if message else "timer"
    label = c(f"⏳  {title}", BOLD + CYAN)
    if target_dt is not None:
        suffix = f"  @ {target_dt.strftime('%H:%M')}"
        if source_label is not None:
            suffix += f" {source_label}"
        label += c(suffix, DIM)
    if countdown(seconds, label=label):
        alerts.trigger(message, sound, opts.repeat, opts.say, opts.no_sound)


# ---------- subcommand handlers ----------


def cmd_at(args: argparse.Namespace) -> None:
    try:
        parsed = parse_time(
            args.time,
            tz_flag=getattr(args, "tz", None),
            config_tz=config.get("timezone"),
        )
    except ValueError as e:
        print(c(f"error: {e}", RED))
        _print_tz_suggestions(e)
        sys.exit(2)
    target = parsed.target
    source_label: str | None = None
    rec_source_tz: str | None = None
    rec_source_label: str | None = None
    if parsed.source_tz is None:
        seconds = (target - datetime.now()).total_seconds()
    else:
        sys_tz = tz.system_tz()
        seconds = (target - datetime.now(tz=sys_tz)).total_seconds()
        src_key = getattr(parsed.source_tz, "key", str(parsed.source_tz))
        sys_key = getattr(sys_tz, "key", str(sys_tz))
        if src_key != sys_key:
            source_label = target.tzname()
            # Persist the IANA zone + the user's typed label for cross-tz
            # background alarms so `chime list` can echo the source wall-clock.
            rec_source_tz = src_key
            rec_source_label = parsed.source_label
    message = " ".join(args.message) if args.message else None
    run_alarm(
        seconds,
        message,
        args,
        target_dt=target,
        source_label=source_label,
        source_tz=rec_source_tz,
        record_label=rec_source_label,
    )


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
    now = datetime.now(tz.system_tz())  # tz-aware: targets are offset-suffixed
    for a in alarms:
        target = datetime.fromisoformat(a["target"])
        remaining = (target - now).total_seconds()
        rem = fmt_duration(remaining) if remaining > 0 else "ringing"
        msg = a["message"] or c("(no message)", DIM)
        line = (
            f"  {c(str(a['pid']).rjust(6), CYAN)}  "
            f"{c(target.strftime('%a %H:%M:%S'), BOLD)}  "
            f"in {c(rem, YELLOW)}  — {msg}"
        )
        if a.get("source_label"):
            src_wall = target.astimezone(ZoneInfo(a["source_tz"])).strftime("%H:%M")
            line += c(f" ({src_wall} {a['source_label']})", DIM)
        print(line)


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


def _system_tz_name() -> str:
    sys_tz = tz.system_tz()
    return getattr(sys_tz, "key", None) or str(sys_tz)


def _config_view() -> None:
    # Only the timezone line is shown; preserved unknown keys stay hidden.
    configured = config.get("timezone")
    sys_name = _system_tz_name()
    if configured:
        print(f"Timezone: {configured} (overrides system: {sys_name})")
    else:
        print(f"Timezone: (not set — using system: {sys_name})")


def _print_tz_suggestions(e: ValueError) -> None:
    """Print an indented 'did you mean' line under an unknown-timezone error.

    Only a plain ``TzResolutionError`` carries a ``spec``; ambiguous/collision
    errors (and non-tz ``ValueError``s) leave it ``None`` and get no suggestions.
    Silent when nothing is close enough."""
    spec = getattr(e, "spec", None)
    if not spec:
        return
    matches = tz.suggest(spec)
    if matches:
        print(c(f"       did you mean: {', '.join(matches)}", RED))


def _config_get(key: str | None) -> None:
    if not key:
        print(c("error: usage: chime config get <key>", RED))
        sys.exit(2)
    value = config.get(key)
    if value is None:
        sys.exit(1)  # unset → non-zero, nothing on stdout (script-friendly)
    print(value)


def _config_set(key: str | None, value: str | None) -> None:
    if not key or value is None:
        print(c("error: usage: chime config set <key> <value>", RED))
        sys.exit(2)
    try:
        if key == "timezone":
            # Resolve once for the echo; store the canonical IANA name (ADR-0002).
            zone, label = tz.resolve(value)
            config.set("timezone", zone.key)
            msg = f"timezone set to {zone.key}"
            if label != zone.key:  # abbrev typed → show it; IANA → omit the parens
                msg += f" ({label})"
            print(c(msg, GREEN))
        else:
            config.set(key, value)
            print(c(f"{key} set to {value}", GREEN))
    except ValueError as e:  # ConfigError (unknown key) or TzResolutionError (bad value)
        print(c(f"error: {e}", RED))
        _print_tz_suggestions(e)
        sys.exit(2)


def cmd_config(args: argparse.Namespace) -> None:
    verb = getattr(args, "verb", None)
    if verb is None:
        _config_view()
        return
    if verb == "get":
        _config_get(args.key)
        return
    if verb == "set":
        _config_set(args.key, args.value)
        return
    if verb == "unset":
        if not args.key:
            print(c("error: usage: chime config unset <key>", RED))
            sys.exit(2)
        config.unset(args.key)
        print(c(f"{args.key} unset", GREEN))
        return
    if verb == "reset":
        config.reset()
        print(c("config reset", GREEN))
        return
    print(c(f"error: unknown config command '{verb}'", RED))
    sys.exit(2)


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
    sp.add_argument("--tz", dest="tz", default=None, help="source timezone (IANA name or abbrev)")
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

    sp = sub.add_parser("config", add_help=False)
    sp.add_argument("verb", nargs="?")  # None | set | unset | reset | get
    sp.add_argument("key", nargs="?")
    sp.add_argument("value", nargs="?")
    sp.set_defaults(func=cmd_config)

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
    # --tz only makes sense for `chime at`; durations are timezone-invariant.
    if "--tz" in flags and (not positional or positional[0] != "at"):
        print(c("error: timezone has no effect on durations", RED))
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
