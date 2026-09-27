import os
import sys


def root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = root()
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
    path = os.path.join(base, "GeminiSpeechAPI")
    os.makedirs(path, exist_ok=True)
    return path


def config_path():
    return os.path.join(config_dir(), "config.json")


def log_dir():
    path = os.path.join(config_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path
