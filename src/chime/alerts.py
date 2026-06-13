"""Cross-platform alarm output: desktop notification + sound + optional TTS.

Backends are selected by `sys.platform`:
  - darwin → osascript / afplay / say
  - linux  → notify-send / paplay / aplay / spd-say (falls back to bell)
  - other  → terminal bell only
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from chime.term import BOLD, DIM, YELLOW, c

DEFAULT_SOUND = "Glass"

_MAC_SOUNDS_DIR = Path("/System/Library/Sounds")
_LINUX_SOUND_DIRS = [
    Path("/usr/share/sounds/freedesktop/stereo"),
    Path("/usr/share/sounds/alsa"),
]
_DEVNULL = subprocess.DEVNULL


def _run_quiet(cmd: list[str]) -> int:
    try:
        return subprocess.run(cmd, stdout=_DEVNULL, stderr=_DEVNULL, check=False).returncode
    except (FileNotFoundError, OSError):
        return -1


# ---------- sounds ----------


def list_sounds() -> list[str]:
    if sys.platform == "darwin" and _MAC_SOUNDS_DIR.exists():
        return sorted(f.stem for f in _MAC_SOUNDS_DIR.glob("*.aiff"))
    if sys.platform.startswith("linux"):
        out: list[str] = []
        for d in _LINUX_SOUND_DIRS:
            if d.exists():
                out.extend(sorted(f.stem for f in d.glob("*.oga")))
                out.extend(sorted(f.stem for f in d.glob("*.wav")))
        return out
    return []


def _resolve_sound_path(sound: str | None) -> Path | None:
    name = sound or DEFAULT_SOUND
    if sys.platform == "darwin":
        path = _MAC_SOUNDS_DIR / f"{name}.aiff"
        if path.exists():
            return path
        fallback = _MAC_SOUNDS_DIR / f"{DEFAULT_SOUND}.aiff"
        return fallback if fallback.exists() else None
    if sys.platform.startswith("linux"):
        for d in _LINUX_SOUND_DIRS:
            for ext in (".oga", ".wav"):
                p = d / f"{name}{ext}"
                if p.exists():
                    return p
        for d in _LINUX_SOUND_DIRS:
            for ext in (".oga", ".wav"):
                p = d / f"bell{ext}"
                if p.exists():
                    return p
        return None
    return None


def play_sound(sound: str | None, repeat: int = 1) -> None:
    repeat = max(1, repeat)
    path = _resolve_sound_path(sound)
    if path is None:
        for _ in range(repeat):
            print("\a", end="", flush=True)
        return
    if sys.platform == "darwin":
        for _ in range(repeat):
            _run_quiet(["afplay", str(path)])
        return
    # Linux: prefer paplay, then aplay
    player = shutil.which("paplay") or shutil.which("aplay") or shutil.which("ffplay")
    if not player:
        for _ in range(repeat):
            print("\a", end="", flush=True)
        return
    args = ["-nodisp", "-autoexit", str(path)] if player.endswith("ffplay") else [str(path)]
    for _ in range(repeat):
        _run_quiet([player, *args])


# ---------- notifications ----------


def notify(title: str, message: str, *, sound: str | None = None) -> None:
    safe_title = (title or "").replace('"', "'").replace("\\", " ")
    safe_msg = (message or "").replace('"', "'").replace("\\", " ")
    if sys.platform == "darwin":
        script = f'display notification "{safe_msg}" with title "{safe_title}"'
        if sound:
            script += f' sound name "{sound}"'
        _run_quiet(["osascript", "-e", script])
        return
    if sys.platform.startswith("linux") and shutil.which("notify-send"):
        _run_quiet(["notify-send", safe_title, safe_msg])
        return
    # Silent fallback — terminal output is the only signal.


# ---------- speech ----------


def speak(message: str) -> None:
    text = message or "Time is up"
    if sys.platform == "darwin":
        with contextlib.suppress(FileNotFoundError, OSError):
            subprocess.Popen(["say", text], stdout=_DEVNULL, stderr=_DEVNULL)
        return
    if sys.platform.startswith("linux"):
        for cmd in (["spd-say", text], ["espeak", text]):
            if shutil.which(cmd[0]):
                with contextlib.suppress(FileNotFoundError, OSError):
                    subprocess.Popen(cmd, stdout=_DEVNULL, stderr=_DEVNULL)
                return


# ---------- composite ----------


def trigger(
    message: str | None, sound: str | None, repeat: int, do_say: bool, silent: bool
) -> None:
    print()
    headline = (message or "ALARM").upper()
    print(c(f"⏰  {headline}", BOLD + YELLOW))
    print(c(f"    {datetime.now().strftime('%a %H:%M:%S')}", DIM))
    print()
    notify("Alarm", message or "Time's up!", sound=None if silent else sound)
    if do_say:
        speak(message or "")
    if not silent:
        play_sound(sound, repeat=repeat)
