<p align="center">
  <img src="assets/banner.png" alt="chime — friendly terminal alarms, timers & pomodoro" width="720">
</p>

<p align="center">
  <a href="https://github.com/MaVericKWareZ/chime/actions/workflows/ci.yml"><img src="https://github.com/MaVericKWareZ/chime/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/chime-cli/"><img src="https://img.shields.io/pypi/v/chime-cli.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/chime-cli/"><img src="https://img.shields.io/pypi/pyversions/chime-cli.svg" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

A no-fuss CLI for the things you actually use timers for: a quick countdown, an alarm at 3pm, and pomodoro rounds when you need to focus. Zero runtime dependencies on macOS and Linux — just the Python standard library (Windows adds one: `tzdata`, for the timezone database it lacks).

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
- Timezone-aware alarms (`at "9am EDT"`, `--tz Asia/Kolkata`) with a default configurable per user
- Pomodoro mode — configurable work / break / rounds
- Stopwatch (count-up)
- Process monitoring — chime when a command finishes (`when` / `monitor`), or when text appears in a command, file, or stream (`watch`)
- Background alarms (`--bg`) that survive shell exit, with `list` / `cancel`
- Native desktop notifications + system sounds on macOS, Linux, and Windows
- Optional spoken alerts (`--say`)
- Zero runtime dependencies on macOS and Linux — just the Python standard library (Windows adds `tzdata`)

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
| `chime at "9am EDT" standup` | Alarm in a source timezone (inline) |
| `chime at 9am --tz Asia/Kolkata` | Same, via the `--tz` flag |
| `chime config set timezone Asia/Kolkata` | Set your default timezone |
| `chime config` | Show effective timezone config |
| `chime pomodoro` | 25/5 × 4 rounds (defaults) |
| `chime pomodoro 50 10 3` | 50m work / 10m break × 3 rounds |
| `chime stopwatch` | Count-up timer |
| `chime when make test` | Run a command; chime when it exits |
| `claude code "…" \| chime monitor "refactor"` | Tee a pipe; chime when it closes |
| `chime watch "curl -s …/health" --until UP` | Poll a command; chime on a match |
| `chime watch --file deploy.log --until Done` | Tail a file for a match |
| `chime watch --stream "npm run dev" --regex listening` | Launch & tee a command; match its output |
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
- `--tz ZONE` — source timezone for the alarm (`EDT`, `Asia/Kolkata`, …); see [Timezones](#timezones). Can't be combined with an inline timezone
- `--say` — speak the message aloud (uses `say` on macOS, `spd-say` / `espeak` on Linux, PowerShell SAPI on Windows)
- `--no-sound` — silent (desktop notification only)

### Duration formats

`10m`, `1h30m`, `90s`, `0.5h`, `45m30s`, `1d`. A bare number is minutes: `chime 30` = 30 min.

### Time formats

`15:30`, `3:30pm`, `9am`, `9:00`, `tomorrow 9am`. Past clock times automatically roll to tomorrow.

## Timezones

By default an alarm fires at the requested wall-clock time in your **system timezone**. You can pin an alarm to a different **source timezone** two ways:

```bash
chime at "9am EDT" standup       # inline, in the time string
chime at 9am --tz Asia/Kolkata   # via the --tz flag
```

Use one or the other — supplying both an inline timezone and `--tz` is an error.

**Accepted abbreviations.** Unambiguous abbreviations resolve as **zone aliases** to a single IANA zone, and full IANA names (`Asia/Kolkata`, `Europe/London`) always work:

| Abbreviation | Zone |
| --- | --- |
| `EST` / `EDT` | `America/New_York` |
| `CDT` | `America/Chicago` |
| `MST` / `MDT` | `America/Denver` |
| `PST` / `PDT` | `America/Los_Angeles` |
| `JST` | `Asia/Tokyo` |
| `KST` | `Asia/Seoul` |
| `AEST` / `AEDT` | `Australia/Sydney` |
| `GMT` / `UTC` | `UTC` |

An abbreviation names the *zone*, not a fixed offset: `EST` and `EDT` both mean New York time, and DST is applied by `zoneinfo` for the target moment — you don't have to know which season you're in. (For a literal fixed offset, use an IANA form like `Etc/GMT+5`.)

**Rejected abbreviations.** Ambiguous abbreviations map to more than one region, so Chime refuses to guess and errors with the candidates — supply the IANA name instead:

| Abbreviation | Could mean |
| --- | --- |
| `IST` | `Asia/Kolkata`, `Europe/Dublin`, `Asia/Jerusalem` |
| `CST` | `America/Chicago`, `Asia/Shanghai`, `America/Havana` |
| `BST` | `Europe/London`, `Asia/Dhaka`, `Pacific/Bougainville` |
| `AST` | `America/Halifax`, `Asia/Riyadh` |

Note `CST` errors even though `CDT` resolves cleanly — the daylight form happens to be unambiguous while the standard form isn't.

**A configured default.** Set a timezone once and every bare `chime at` uses it:

```bash
chime config set timezone Asia/Kolkata
```

Abbreviations are resolved to their IANA name when you set them (`chime config set timezone EDT` stores `America/New_York` and echoes back the typed form). The **effective timezone** for any command is resolved in order: inline timezone → `--tz` → configured default → system timezone.

`chime config` shows the current setting; `chime config get timezone` prints just the value (script-friendly); `chime config unset timezone` clears it; `chime config reset` wipes the whole config.

**Config file.** Settings live in a single JSON file:

- **POSIX (macOS / Linux):** `$XDG_CONFIG_HOME/chime/config.json` (defaults to `~/.config/chime/config.json`).
- **Windows:** `%APPDATA%\chime\config.json`.

## Process monitoring

Chime can fire on an *event* instead of the clock — when a command finishes, or when text appears in a command's output, a file, or a stream. These verbs reuse the same alert stack (`--sound`, `--say`, `--no-sound`, `--repeat`) and add no runtime dependencies — they're pure Python standard library.

### Completion notifications — `chime when`

`chime when <command>` runs a command as a foreground child, streams its output through untouched, and fires a **Completion notification** when the process exits:

```bash
chime when make test                 # chime the moment the suite finishes
chime when --only-fail make deploy   # only chime on a non-zero exit
chime when -- --weird-tool …         # -- escapes a command that starts with a dash
```

Chime parses its own options up to the first bare token; that token and everything after it is the wrapped command, passed through verbatim (so `chime when make test --verbose -j4` sends `--verbose -j4` to `make`, not to Chime). Put Chime's own flags *before* the command.

It's a transparent wrapper — colors, progress bars, and interactive prompts work exactly as if you hadn't wrapped it — and it **propagates the child's exit code**, so `chime when make test && ./deploy.sh` and CI gating behave identically to running the command directly. Spawn failures follow shell conventions (`127` command-not-found, `126` found-but-not-executable); a signal death maps to `128 + signum`.

The default line names the command, exit code, and elapsed time:

```
🔔  `make test` finished — exit 0 (4m 12s)
```

`--only-fail` chimes only on a non-zero exit, `--only-pass` only on success; specifying both is an error. Hitting Ctrl-C cancels the command and chimes *nothing* (exit `130`) — you're never alerted about something you just killed. A command that dies of a signal you *didn't* send (an OOM kill, a segfault) is a real, failed completion and does chime.

> **Platform note.** On POSIX the message names the signal (`killed by SIGSEGV`); Windows can't, so it degrades to `exited abnormally (code N)`.

### Pipe form — `chime monitor`

`… | chime monitor [label]` tees a stream through to your terminal byte-for-byte and fires when the upstream producer closes:

```bash
claude code "refactor the auth module" | chime monitor "refactor auth"
```

Because a pipe carries no exit status, the line reads `stream ended` (with elapsed) rather than an exit code — Chime won't pretend to know a status it can't see. For the same reason, `--only-fail` / `--only-pass` are errors here.

### Watch — fire on a content match

`chime watch` fires a **Watch** when a content predicate matches an observed source. The source kind is always explicit — never guessed from disk state — and there are two kinds.

A **Poll source** is a snapshot command Chime re-runs on an interval, matching the whole output each run. A bare command is a Poll source — the flagship readiness case:

```bash
chime watch "curl -s localhost:8080/health" --until UP        # chime when the service is up
chime watch "kubectl get pods" --until Running --interval 10s
```

`--interval` sets the cadence (default 5s) and applies only to Poll sources. A Poll source is one-shot only; `--keep-watching` on a poll is an error.

A **Stream source** is read as a line stream, matching each new line once. `--file` tails a file:

```bash
chime watch --file deploy.log --until Done    # chime when Done is appended
```

The file watch matches only content appended *after* the watch starts (a stale `Done` from yesterday won't fire instantly), waits for the file to appear if it doesn't exist yet, and survives log rotation/truncation by re-opening. Note the source is named with `--file` — a bare first argument to `watch` is always a Poll *command*, never a file path.

`--stream` launches a command and tees it, matching each line across **both stdout and stderr**:

```bash
chime watch --stream "npm run dev" --regex "listening on"    # chime when the dev server is up
```

The wrapped process is **never killed by a match or a timeout** — Chime keeps teeing until the child exits on its own (propagating its code) or you Ctrl-C it. So `--stream`-watching a live server for errors never takes the server down. (`--stream` combined with `--interval`, or with `--file`, is an error — a stream isn't polled, and a watch names one source.)

**Predicates.** A bare trailing argument and `--until <pattern>` mean the same thing. Matching is substring by default (case-sensitive); `--regex` opts into a regular expression (`--regex "ERROR|FATAL"`), and `--ignore-case` applies to either.

**Firing.** A watch is one-shot by default — it fires on the first match and stops. On a Stream source, `--keep-watching` fires on *every* new matching line instead (handy for tailing `app.log` for each `ERROR`).

**Timeout.** `--timeout 10m` chimes a "timed out" alert if nothing matched in time. A poll or file watch then exits (code `1`); a `--stream` watch chimes but keeps teeing (never kills the child). A watch is scriptable — exit `0` on match, `1` on timeout, `130` on Ctrl-C — and Ctrl-C stops it silently.

## Platform support

| Platform | Notifications | Sound | Speech |
| --- | --- | --- | --- |
| macOS | `osascript` | `afplay` + system sounds | `say` |
| Linux | `notify-send` (libnotify) | `paplay` / `aplay` | `spd-say` / `espeak` |
| Windows | PowerShell toast (Win 10+) | `winsound` (stdlib) | PowerShell SAPI |

Linux users typically already have these tools; on a fresh system: `sudo apt install libnotify-bin pulseaudio-utils` (Debian / Ubuntu) gets you notifications + sound.

Windows has no system IANA timezone database, so the install pulls in `tzdata` (the only runtime dependency, and only on Windows) to power the timezone features. macOS and Linux read zones from the OS and install nothing extra.

## Background alarms

When you use `--bg`, chime detaches from your shell — you can close the terminal and the alarm still fires.

- **POSIX (macOS / Linux):** double-fork + `setsid`. State at `$XDG_STATE_HOME/chime/alarms.json` (defaults to `~/.local/state/chime/alarms.json`).
- **Windows:** `subprocess.Popen` with `DETACHED_PROCESS` flags. State at `%LOCALAPPDATA%\chime\alarms.json`.

For an alarm set in a non-local source timezone, `chime list` appends the source wall-clock and label in parens (e.g. `Fri 18:30:00 … (09:00 EDT)`) so you can audit what you scheduled.

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
