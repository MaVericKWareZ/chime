# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Windows support: `winsound` for system sound aliases, PowerShell toast notifications (Win 10+), PowerShell SAPI for `--say`, and `subprocess.Popen` with `DETACHED_PROCESS` for `--bg`.
- Windows added to CI test matrix.
- `Operating System :: Microsoft :: Windows` PyPI classifier.

### Changed
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
