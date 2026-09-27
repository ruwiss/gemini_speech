import subprocess
import sys

from PyQt6.QtGui import QGuiApplication
from PyQt6.QtCore import QTimer


def paste_text(text):
    text = (text or "").strip()
    if not text:
        return False
    if sys.platform.startswith("linux"):
        from . import desktop
        return desktop.paste(text)
    QGuiApplication.clipboard().setText(text)
    QTimer.singleShot(40, _press)
    return True


def _press():
    if sys.platform == "win32":
        import ctypes
        user32 = ctypes.windll.user32
        user32.keybd_event(0x11, 0, 0, 0)
        user32.keybd_event(0x56, 0, 0, 0)
        user32.keybd_event(0x56, 0, 2, 0)
        user32.keybd_event(0x11, 0, 2, 0)
        return
    if sys.platform == "darwin":
        subprocess.Popen([
            "osascript", "-e",
            'tell application "System Events" to keystroke "v" using command down',
        ])
        return
