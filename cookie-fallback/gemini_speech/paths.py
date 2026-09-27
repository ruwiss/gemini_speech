import os
import sys


def root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = root()
SERVER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "server",
    "speech_server.py",
)


def extension_dir():
    candidates = [os.path.join(ROOT, "extension")]
    if sys.platform == "darwin":
        candidates.append(os.path.join(os.path.dirname(ROOT), "Resources", "extension"))
    bundled = getattr(sys, "_MEIPASS", "")
    if bundled:
        candidates.append(os.path.join(bundled, "extension"))
    for path in candidates:
        if os.path.isdir(path):
            return path
    return candidates[0]


EXTENSION = extension_dir()
ICON = os.path.join(ROOT, "assets", "icon.png")
if not os.path.isfile(ICON):
    bundled = getattr(sys, "_MEIPASS", "")
    if bundled and os.path.isfile(os.path.join(bundled, "assets", "icon.png")):
        ICON = os.path.join(bundled, "assets", "icon.png")


def config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, "GeminiSpeech")
    os.makedirs(path, exist_ok=True)
    return path


def config_path():
    return os.path.join(config_dir(), "config.json")


def cookies_path():
    return os.path.join(config_dir(), "browser-cookies.txt")


def host_manifest():
    return os.path.join(config_dir(), "com.gemini.speech.json")


def log_dir():
    path = os.path.join(config_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def log_path():
    return os.path.join(log_dir(), "speech.log")


def err_path():
    return os.path.join(log_dir(), "speech.err.log")


def pid_path():
    return os.path.join(config_dir(), "server.pid")
