import sys
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from . import messages

WIN_KEYS = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B,
    **{str(n): 0x30 + n for n in range(10)},
    **{chr(ord("a") + i): 0x41 + i for i in range(26)},
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
}
WIN_MODS = {"alt": 1, "ctrl": 2, "control": 2, "shift": 4, "meta": 8, "win": 8, "super": 8}
RESERVED = {
    frozenset({"alt", "tab"}), frozenset({"ctrl", "esc"}), frozenset({"alt", "esc"}),
    frozenset({"ctrl", "alt", "delete"}), frozenset({"meta", "l"}),
    frozenset({"ctrl", "shift", "esc"}), frozenset({"alt", "f4"}),
    frozenset({"meta", "d"}), frozenset({"meta", "e"}), frozenset({"meta", "r"}),
    frozenset({"meta", "tab"}),
}


def parts(text):
    aliases = {"control": "ctrl", "win": "meta", "super": "meta", "option": "alt", "cmd": "meta"}
    out = []
    for part in str(text).split("+"):
        part = part.strip().lower()
        if part:
            out.append(aliases.get(part, part))
    return out


def parse_windows(text):
    mods, key = 0, None
    for part in parts(text):
        if part in WIN_MODS:
            mods |= WIN_MODS[part]
        elif key is None and part in WIN_KEYS:
            key = WIN_KEYS[part]
        else:
            return None, None
    if key is None:
        return None, None
    return mods, key


def held(text):
    if sys.platform != "win32":
        return False
    mods, key = parse_windows(text)
    if key is None:
        return False
    import ctypes
    user32 = ctypes.windll.user32
    down = lambda code: bool(user32.GetAsyncKeyState(code) & 0x8000)
    if not down(key):
        return False
    keys = [part for part in parts(text) if part in WIN_KEYS]
    wanted = set(parts(text)) - set(keys)
    mapping = {"alt": 0x12, "ctrl": 0x11, "shift": 0x10, "meta": 0x5B}
    for name, code in mapping.items():
        if down(code) != (name in wanted):
            return False
    return True


def same_shortcut(a, b):
    left, right = parts(a), parts(b)
    return bool(left) and len(left) == len(right) and frozenset(left) == frozenset(right)


def windows_conflict(text, probe=True, current=""):
    if current and same_shortcut(text, current):
        return ""
    if sys.platform != "win32":
        return ""
    if frozenset(parts(text)) in RESERVED:
        return messages.SHORTCUT_RESERVED % text
    if not probe:
        return ""
    mods, key = parse_windows(text)
    if key is None:
        return messages.SHORTCUT_UNREADABLE
    import ctypes
    user32 = ctypes.windll.user32
    slot = 0x5B21
    if user32.RegisterHotKey(None, slot, mods | 0x4000, key):
        user32.UnregisterHotKey(None, slot)
        return ""
    return messages.SHORTCUT_TAKEN % text


class Hotkey(QObject):
    pressed = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._thread = None
        self._thread_id = 0
        self._pending = False
        self._error = ""

    def take(self):
        fired = self._pending
        self._pending = False
        return fired

    def take_error(self):
        text = self._error
        self._error = ""
        return text

    def _mark(self):
        self._pending = True

    def start(self, shortcut):
        self.stop()
        if not str(shortcut or "").strip():
            return False
        if sys.platform == "win32":
            mods, key = parse_windows(shortcut)
            if key is None:
                self.failed.emit(messages.SHORTCUT_UNREADABLE_NAMED % shortcut)
                return False
            reason = windows_conflict(shortcut)
            if reason.startswith("Windows already uses"):
                self.failed.emit(reason)
                return False
            self._thread = threading.Thread(
                target=self._win_loop, args=(mods, key, shortcut), daemon=True
            )
            self._thread.start()
            return True
        return self._start_pynput(shortcut)

    def stop(self):
        if sys.platform == "win32" and self._thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread:
            self._thread.join(timeout=1.2)
        self._thread = None
        self._thread_id = 0

    def _win_loop(self, mods, key, shortcut):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        if not user32.RegisterHotKey(None, 1, mods | 0x4000, key):
            self._error = messages.SHORTCUT_TAKEN % shortcut
            return
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:
                    self._pending = True
                if msg.message == 0x0012:
                    break
        finally:
            user32.UnregisterHotKey(None, 1)

    def _start_pynput(self, shortcut):
        try:
            from pynput import keyboard
        except ImportError:
            self.failed.emit(messages.PYNPUT_MISSING)
            return False
        key_name = [part for part in parts(shortcut) if part not in WIN_MODS]
        if len(key_name) != 1:
            self.failed.emit(messages.SHORTCUT_UNREADABLE_NAMED % shortcut)
            return False
        mapping = _pynput_hotkey(shortcut)
        self._listener = keyboard.GlobalHotKeys({mapping: self._mark})
        self._listener.start()
        self._thread = None
        return True


def _pynput_hotkey(text):
    names = {"ctrl": "<ctrl>", "alt": "<alt>", "shift": "<shift>", "meta": "<cmd>"}
    bits = []
    key = ""
    for part in parts(text):
        if part in names:
            bits.append(names[part])
        else:
            key = part
    return "+".join(bits + [key])
