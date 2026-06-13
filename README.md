<p align="center">
  <img src="assets/banner.png" alt="chime — friendly terminal alarms, timers & pomodoro" width="720">
</p>

<p align="center">
  <a href="https://github.com/MaVericKWareZ/chime/actions/workflows/ci.yml"><img src="https://github.com/MaVericKWareZ/chime/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/chime-cli/"><img src="https://img.shields.io/pypi/v/chime-cli.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/chime-cli/"><img src="https://img.shields.io/pypi/pyversions/chime-cli.svg" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

A no-fuss CLI for the things you actually use timers for: a quick countdown, an alarm at 3pm, and pomodoro rounds when you need to focus. Zero runtime dependencies — just the Python standard library.

```text
$ chime 10m "tea is ready"
⏳  tea is ready
  target 16:42:11  ·  10m from now
  Ctrl-C to cancel

  09:58
```

## Features

- Countdown timers with natural durations (`10m`, `1h30m`, `90s`, `0.5h`)
- Clock-time alarms (`at 9am`, `at 15:30`, `at "tomorrow 9am"`)
- Pomodoro mode — configurable work / break / rounds
- Stopwatch (count-up)
- Background alarms (`--bg`) that survive shell exit, with `list` / `cancel`
- Native desktop notifications + system sounds on macOS, Linux, and Windows
- Optional spoken alerts (`--say`)
- Zero runtime dependencies — just the Python standard library

## Install

**Homebrew (macOS / Linux):**

```bash
brew install MaVericKWareZ/tap/chime
```

**pipx (cross-platform, recommended for Windows):**

```bash
pipx install chime-cli
# or
pip install --user chime-cli
```

**From source:**

```bash
git clone https://github.com/MaVericKWareZ/chime
cd chime
pipx install .
```

Any of these puts a `chime` command on your PATH.

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
- `--say` — speak the message aloud (uses `say` on macOS, `spd-say` / `espeak` on Linux, PowerShell SAPI on Windows)
- `--no-sound` — silent (desktop notification only)

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

Linux users typically already have these tools; on a fresh system: `sudo apt install libnotify-bin pulseaudio-utils` (Debian / Ubuntu) gets you notifications + sound.

## Background alarms

When you use `--bg`, chime detaches from your shell — you can close the terminal and the alarm still fires.

- **POSIX (macOS / Linux):** double-fork + `setsid`. State at `$XDG_STATE_HOME/chime/alarms.json` (defaults to `~/.local/state/chime/alarms.json`).
- **Windows:** `subprocess.Popen` with `DETACHED_PROCESS` flags. State at `%LOCALAPPDATA%\chime\alarms.json`.

Stale entries from killed processes are pruned automatically the next time you run `chime list` or `chime cancel`.

## Development

```bash
git clone https://github.com/MaVericKWareZ/chime
cd chime
python -m venv .venv && source .venv/bin/activate
make install      # editable install + dev deps + pre-commit hooks
make help         # discover every dev / build / release target
```

`make test`, `make lint`, `make fmt`, `make build` are the common ones. See [CONTRIBUTING.md](CONTRIBUTING.md) for the contributor guide and the release process.

## Links

- [Changelog](CHANGELOG.md) — what changed, version by version
- [Contributing](CONTRIBUTING.md) — dev setup, code style, release flow
- [Security policy](SECURITY.md) — how to report a vulnerability
- [Issue tracker](https://github.com/MaVericKWareZ/chime/issues)

## License

[MIT](LICENSE) © Sarthak Mahapatra
