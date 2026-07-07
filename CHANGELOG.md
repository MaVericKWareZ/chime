# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/MaVericKWareZ/chime/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MaVericKWareZ/chime/releases/tag/v0.1.0
