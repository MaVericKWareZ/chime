"""Cross-platform alarm output: desktop notification + sound + optional TTS.

Backends are selected by `sys.platform`:
  - darwin → osascript / afplay / say
  - linux  → notify-send / paplay / aplay / spd-say (falls back to bell)
  - win32  → winsound (stdlib) + PowerShell toast / SAPI
  - other  → terminal bell only
"""

from __future__ import annotations

import base64
import contextlib
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from chime.term import BOLD, DIM, YELLOW, c

DEFAULT_SOUND = "Glass" if sys.platform != "win32" else "SystemAsterisk"

_MAC_SOUNDS_DIR = Path("/System/Library/Sounds")
_LINUX_SOUND_DIRS = [
    Path("/usr/share/sounds/freedesktop/stereo"),
    Path("/usr/share/sounds/alsa"),
]
_WIN_SOUND_ALIASES = (
    "SystemAsterisk",
    "SystemExclamation",
    "SystemHand",
    "SystemQuestion",
    "SystemDefault",
)
_DEVNULL = subprocess.DEVNULL


def _ps_encoded(script: str) -> str:
    """PowerShell -EncodedCommand input: UTF-16-LE base64. Sidesteps shell quoting."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


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
    if sys.platform == "win32":
        return list(_WIN_SOUND_ALIASES)
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
    if sys.platform == "win32":
        _play_sound_windows(sound, repeat)
        return
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


def _play_sound_windows(sound: str | None, repeat: int) -> None:
    try:
        import winsound  # noqa: PLC0415 — Windows-only stdlib module
    except ImportError:
        for _ in range(repeat):
            print("\a", end="", flush=True)
        return
    alias = sound if sound in _WIN_SOUND_ALIASES else DEFAULT_SOUND
    flags = winsound.SND_ALIAS | winsound.SND_NODEFAULT
    for _ in range(repeat):
        with contextlib.suppress(RuntimeError, OSError):
            winsound.PlaySound(alias, flags)


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
    if sys.platform == "win32":
        _notify_windows(safe_title, safe_msg)
        return
    # Silent fallback — terminal output is the only signal.


def _notify_windows(title: str, message: str) -> None:
    """Best-effort Windows toast via PowerShell + WinRT. No-ops on failure."""
    if not shutil.which("powershell"):
        return
    # Escape single quotes for the embedded XML literal.
    t = title.replace("'", "&apos;").replace("<", "&lt;").replace(">", "&gt;")
    m = message.replace("'", "&apos;").replace("<", "&lt;").replace(">", "&gt;")
    xml = (
        f"<toast><visual><binding template='ToastText02'>"
        f"<text id='1'>{t}</text><text id='2'>{m}</text>"
        f"</binding></visual></toast>"
    )
    script = (
        "$ErrorActionPreference = 'SilentlyContinue';"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f'$xml.LoadXml("{xml}");'
        "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('chime').Show($toast)"
    )
    _run_quiet(["powershell", "-NoProfile", "-EncodedCommand", _ps_encoded(script)])


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
        return
    if sys.platform == "win32" and shutil.which("powershell"):
        # SAPI via PowerShell — fire and forget.
        safe = text.replace('"', "'").replace("\\", " ")
        script = (
            "Add-Type -AssemblyName System.Speech;"
            f'(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak("{safe}")'
        )
        with contextlib.suppress(FileNotFoundError, OSError):
            subprocess.Popen(
                ["powershell", "-NoProfile", "-EncodedCommand", _ps_encoded(script)],
                stdout=_DEVNULL,
                stderr=_DEVNULL,
            )


# ---------- composite ----------


def deliver(
    title: str,
    message: str,
    *,
    sound: str | None,
    repeat: int,
    do_say: bool,
    silent: bool,
) -> None:
    """Fan an alert out to the desktop notification, speech, and sound backends.

    The terminal surface (the timer header, the completion line) is rendered by
    the caller; this is delivery only, shared across every trigger (ADR-0004).
    """
    notify(title, message, sound=None if silent else sound)
    if do_say:
        speak(message)
    if not silent:
        play_sound(sound, repeat=repeat)


def trigger(
    message: str | None, sound: str | None, repeat: int, do_say: bool, silent: bool
) -> None:
    print()
    headline = (message or "ALARM").upper()
    print(c(f"⏰  {headline}", BOLD + YELLOW))
    print(c(f"    {datetime.now().strftime('%a %H:%M:%S')}", DIM))
    print()
    deliver(
        "Alarm",
        message or "Time's up!",
        sound=sound,
        repeat=repeat,
        do_say=do_say,
        silent=silent,
    )
