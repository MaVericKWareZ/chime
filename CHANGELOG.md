# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-07-20

### Added
- Process monitoring — three new event-driven verbs that fire Chime's existing alert stack (sound, desktop notification, `--say`, `--repeat`) on a process event rather than a clock.
- `chime when <command>` — a **Completion notification** wrapper: runs a command as a foreground child with inherited stdio (colors, prompts, and interactivity untouched), times the run, and chimes when it exits with the command, exit code, and elapsed time (`🔔  \`make test\` finished — exit 0 (4m 12s)`). It's a transparent wrapper — the child's exit code is propagated, so it drops into `&&` chains and CI gating unchanged. Chime's own options go before the command (model-A argv grammar); everything from the first bare token on is passed through verbatim, with `--` as an explicit escape. Spawn failures map to shell conventions (127 not-found, 126 not-executable); a foreign signal death maps to `128 + signum` and names the signal on POSIX (`killed by SIGSEGV`), degrading to `exited abnormally (code N)` on Windows.
- `chime when --only-fail` / `--only-pass` — firing filters that gate whether the alert fires (the exit code is always propagated); specifying both is an error.
- Ctrl-C (or a SIGTERM aimed at Chime) during `chime when` is forwarded to the child, fires **no** alert (outcome `aborted`), and exits 130; a signal Chime did not send is still a real, chimed completion.
- `… | chime monitor` — the pipe form of a Completion notification: tees stdin→stdout byte-faithfully and fires when the upstream producer closes (`🔔  stream ended (4m 12s)`). Accepts an optional trailing label for the message, exits 0 on clean EOF, and exits quietly (141) like a SIGPIPE-aware Unix filter when a downstream reader closes early. `--only-fail`/`--only-pass` with `monitor` are an error (a pipe carries no exit status).
- `chime watch` — fires when a content predicate matches an observed source, distinguishing a **Poll source** (a snapshot command re-run on `--interval`, default 5s — `chime watch "curl -s localhost:8080/health" --until UP`) from a **Stream source** (`--file <path>` tails a log; `--stream "<cmd>"` launches and tees a command). A bare command defaults to a Poll source; source kind is always explicit, never inferred from disk state.
- `chime watch --file <path>` — tails a file, matching each newly-appended line: seeks to EOF at start (a stale match never fires), waits for the file if it doesn't exist yet then tails from its top, and follows `logrotate`-style rotation/truncation by re-opening from the top of the new file.
- `chime watch --stream "<cmd>"` — launches a command, tees both stdout and stderr back to their own fds, and matches per line across both. The wrapped process is **never killed** by a match or a timeout — Chime keeps teeing until the child exits on its own (propagating its code) or you Ctrl-C (`aborted`), so watching a live server's logs never takes the server down.
- `chime watch` predicates — case-sensitive substring by default; `--regex` opts into `re.search`; `--ignore-case` applies to either. A bare trailing positional and `--until <pattern>` set the same predicate. Poll sources match the whole snapshot; Stream sources match per line.
- `chime watch --timeout <dur>` — fires a `timed_out` alert if nothing matched in time (poll/file sources then exit 1; a `--stream` source keeps teeing). `--keep-watching` fires on every new matching line of a file or `--stream` source (an error on a Poll source). Default is one-shot: fire once on the first match and stop. Exit codes: 0 on match, 1 on timeout, 130 on Ctrl-C.
- `when`, `monitor`, and `watch` documented in `chime help` and a new **Process monitoring** section of the README.

### Changed
- `alerts.deliver(title, message, …)` extracted from `alerts.trigger()` so timers, completion notifications, and watches share one delivery path; the existing timer output is byte-identical. No new runtime dependencies — `when`/`monitor`/`watch` are pure stdlib (`subprocess`, `threading`, `os`, `re`, `signal`). Every existing command behaves exactly as before.

## [0.2.0] - 2026-07-07

### Added
- Timezone-aware alarms: `chime at` accepts a source timezone inline (`chime at "9am EDT" standup`) or via a new `--tz` flag (`chime at 9am --tz Asia/Kolkata`). Unambiguous abbreviations (`EST`/`EDT`, `PST`/`PDT`, `CDT`, `MST`/`MDT`, `JST`, `KST`, `AEST`/`AEDT`, `GMT`/`UTC`) resolve as zone aliases to a single IANA zone, with DST applied by `zoneinfo` at the target moment; full IANA names always work. The countdown header and `chime list` show the source-timezone label only when it differs from local, so same-timezone usage is unchanged.
- Ambiguous timezone abbreviations (`IST`, `CST`, `BST`, `AST`) now error at parse time with a disambiguation list of candidate IANA zones instead of silently picking one; `CDT` and other unambiguous abbreviations are unaffected.
- Configurable default timezone via a new config subsystem: `chime config set timezone <zone>` persists a default so bare `chime at` commands use it. Abbreviations are resolved to their canonical IANA name on set. Also `chime config` (view), `chime config get <key>`, `chime config unset <key>`, and `chime config reset`. Config lives in a single JSON file at `$XDG_CONFIG_HOME/chime/config.json` (`%APPDATA%\chime\config.json` on Windows), with atomic writes, unknown-key preservation, and warn-and-degrade on corrupt files.
- Fuzzy "did you mean" suggestions for mistyped IANA zone names when setting a timezone (`chime config set timezone londn` → suggests `Europe/London`, `Europe/Lisbon`).
- Effective-timezone resolution chain — inline → `--tz` → configured default → system timezone — with POSIX `$TZ` honored transparently via the system-timezone fallback. Supplying both an inline timezone and `--tz` is rejected.
- Windows support: `winsound` for system sound aliases, PowerShell toast notifications (Win 10+), PowerShell SAPI for `--say`, and `subprocess.Popen` with `DETACHED_PROCESS` for `--bg`.
- Windows added to CI test matrix.
- `Operating System :: Microsoft :: Windows` PyPI classifier.
- `tzdata` as a runtime dependency on Windows only (via a `platform_system == 'Windows'` environment marker), so `zoneinfo` can resolve IANA zones on a platform that ships no system timezone database. macOS and Linux stay dependency-free.

### Changed
- Background alarm records now store `target` as a timezone-aware, offset-suffixed ISO timestamp (plus optional `source_tz` / `source_label` for cross-timezone alarms). Existing `alarms.json` files with naive timestamps are migrated silently and automatically on the first save after upgrade — no `chime migrate` step, and pending alarms keep firing correctly.
- Background state file lives under `%LOCALAPPDATA%\chime\` on Windows (still `$XDG_STATE_HOME/chime/` on POSIX).
- Default sound on Windows is `SystemAsterisk` (no `Glass.aiff` available).
- Bumped GitHub Actions: `checkout` 4→6, `setup-python` 5→6, `upload-artifact` 4→7, `download-artifact` 4→8.
- README: documented `brew install MaVericKWareZ/tap/chime` install path.

## [0.1.0]

### Added
- Countdown timer with friendly duration syntax (`10m`, `1h30m`, `90s`, `0.5h`).
- Clock-time alarms (`chime at 9am`, `at 15:30`, `at "tomorrow 9am"`).
- Background alarms (`--bg`) that survive shell exit, with `list` / `cancel <id|all>` management.
- Pomodoro mode with configurable work / break / rounds.
- Stopwatch mode.
- macOS desktop notifications + system sounds via `osascript` / `afplay`.
- Linux desktop notifications + sound via `notify-send` / `paplay` / `aplay`.
- Optional spoken alerts via `say` / `spd-say` / `espeak`.

[Unreleased]: https://github.com/MaVericKWareZ/chime/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/MaVericKWareZ/chime/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/MaVericKWareZ/chime/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/MaVericKWareZ/chime/releases/tag/v0.1.0
