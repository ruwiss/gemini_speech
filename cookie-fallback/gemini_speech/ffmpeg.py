import os
import sys

from . import messages


_CACHED = ""


def available():
    return bool(binary())


def require():
    path = binary()
    if not path:
        raise RuntimeError(messages.FFMPEG_MISSING)
    return path


def binary():
    global _CACHED
    if _CACHED and os.path.isfile(_CACHED):
        return _CACHED
    _CACHED = _locate()
    return _CACHED


def install_command():
    if sys.platform == "win32":
        return "winget install --id Gyan.FFmpeg -e"
    if sys.platform == "darwin":
        return "brew install ffmpeg"
    if os.path.isfile("/usr/bin/apt-get") or os.path.isfile("/usr/bin/apt"):
        return "sudo apt install -y ffmpeg"
    if os.path.isfile("/usr/bin/dnf"):
        return "sudo dnf install -y ffmpeg"
    if os.path.isfile("/usr/bin/pacman"):
        return "sudo pacman -S --noconfirm ffmpeg"
    if os.path.isfile("/usr/bin/zypper"):
        return "sudo zypper install -y ffmpeg"
    if os.path.isfile("/sbin/apk") or os.path.isfile("/usr/bin/apk"):
        return "sudo apk add ffmpeg"
    return "Install the ffmpeg package from your system, then leave this window open."


def _locate():
    names = ("ffmpeg.exe", "ffmpeg") if sys.platform == "win32" else ("ffmpeg",)
    for folder in _folders():
        for name in names:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
    return ""


def _folders():
    found = []
    seen = set()

    def add(folder):
        folder = os.path.normpath(os.path.expandvars(folder or ""))
        key = folder.lower() if sys.platform == "win32" else folder
        if not folder or key in seen or not os.path.isdir(folder):
            return
        seen.add(key)
        found.append(folder)

    for folder in os.environ.get("PATH", "").split(os.pathsep):
        add(folder)
    if sys.platform == "win32":
        for folder in _windows_path():
            add(folder)
        for folder in _winget_bins():
            add(folder)
    elif sys.platform == "darwin":
        add("/opt/homebrew/bin")
        add("/usr/local/bin")
    else:
        add("/usr/bin")
        add("/usr/local/bin")
        add(os.path.expanduser("~/.local/bin"))
    return found


def _windows_path():
    import winreg
    found = []
    keys = (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    )
    for root, name in keys:
        try:
            with winreg.OpenKey(root, name) as handle:
                value, _ = winreg.QueryValueEx(handle, "Path")
        except OSError:
            continue
        found.extend(str(value).split(os.pathsep))
    return found


def _winget_bins():
    local = os.environ.get("LOCALAPPDATA") or ""
    packages = os.path.join(local, "Microsoft", "WinGet", "Packages")
    found = []
    links = os.path.join(local, "Microsoft", "WinGet", "Links")
    if os.path.isdir(links):
        found.append(links)
    if not os.path.isdir(packages):
        return found
    for entry in os.scandir(packages):
        if not entry.is_dir() or "ffmpeg" not in entry.name.lower():
            continue
        for dirpath, _dirs, files in os.walk(entry.path):
            if any(name.lower() == "ffmpeg.exe" for name in files):
                found.append(dirpath)
    return found
