# chime

> Friendly terminal alarms, timers & pomodoro for macOS, Linux, and Windows.

[![CI](https://github.com/MaVericKWareZ/chime/actions/workflows/ci.yml/badge.svg)](https://github.com/MaVericKWareZ/chime/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/chime-cli.svg)](https://pypi.org/project/chime-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/chime-cli.svg)](https://pypi.org/project/chime-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A no-fuss CLI for the things you actually use timers for: a quick countdown, an alarm at 3pm, and pomodoro rounds when you need to focus. Zero dependencies, just the Python standard library.

```
$ chime 10m "tea is ready"
⏳  tea is ready
  target 16:42:11  ·  10m from now
  Ctrl-C to cancel

  09:58
```

## Install

**Homebrew (macOS/Linux):**

```bash
brew install MaVericKWareZ/tap/chime
```

**pipx (any platform):**

```bash
pipx install chime-cli      # recommended for non-mac users — isolates the install
# or
pip install --user chime-cli
```

Either gets you the `chime` command on your PATH.

### From source

```bash
git clone https://github.com/MaVericKWareZ/chime
cd chime
pipx install .
```

## Usage

| Command | What it does |
| --- | --- |
| `chime 10m "tea"` | Countdown timer (foreground) |
| `chime 1h30m` | Same, longer |
| `chime --bg 25m focus` | Set alarm in background, get your prompt back |
| `chime at 9:30am standup` | Alarm at clock time |
| `chime at 15:30 "pick up package"` | 24h clock |
| `chime at "tomorrow 9am"` | Skip ahead one day |
| `chime pomodoro` | 25/5 × 4 rounds (defaults) |
| `chime pomodoro 50 10 3` | 50m work / 10m break × 3 rounds |
| `chime stopwatch` | Count-up timer |
| `chime list` | Show active background alarms |
| `chime cancel 1234` | Cancel one (by id from `chime list`) |
| `chime cancel all` | Cancel everything |
| `chime sounds` | List available alarm sounds |
| `chime sounds Hero` | Preview a sound |
| `chime help` | Full help |

### Options

Available on any alarm-setting command, in any position:

- `--bg` — run in background, return immediately
- `--sound NAME` — use a different alert sound (`chime sounds` to list)
- `--repeat N` — repeat the alert sound N times (default 3)
- `--say` — speak the message aloud (uses `say` on macOS, `spd-say`/`espeak` on Linux)
- `--no-sound` — silent — desktop notification only

### Duration formats

`10m`, `1h30m`, `90s`, `0.5h`, `45m30s`, `1d`. A bare number is minutes: `chime 30` = 30 min.

### Time formats

`15:30`, `3:30pm`, `9am`, `9:00`, `tomorrow 9am`. Past clock times automatically roll to tomorrow.

## Platform support

| Platform | Notifications | Sound | Speech |
| --- | --- | --- | --- |
| macOS | `osascript` | `afplay` + system sounds | `say` |
| Linux | `notify-send` (libnotify) | `paplay` / `aplay` | `spd-say` / `espeak` |
| Windows | PowerShell toast (Win 10+) | `winsound` (stdlib) | PowerShell SAPI |

Linux users typically already have these tools; on a fresh system: `sudo apt install libnotify-bin pulseaudio-utils` (Debian/Ubuntu) gets you notifications + sound.

## Background alarms

When you use `--bg`, chime detaches from your shell — you can close the terminal and the alarm still fires.

- **POSIX (macOS/Linux):** double-fork + `setsid`. State at `$XDG_STATE_HOME/chime/alarms.json` (defaults to `~/.local/state/chime/alarms.json`).
- **Windows:** `subprocess.Popen` with `DETACHED_PROCESS` flags. State at `%LOCALAPPDATA%\chime\alarms.json`.

Stale entries from killed processes are pruned automatically the next time you run `chime list` or `chime cancel`.

## Development

```bash
git clone https://github.com/MaVericKWareZ/chime
cd chime
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pre-commit install   # auto-lint on commit

pytest               # run tests
ruff check .         # lint
ruff format .        # auto-format
python -m build      # build sdist + wheel
```

## License

[MIT](LICENSE).
