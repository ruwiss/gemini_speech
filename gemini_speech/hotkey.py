import sys
import threading

from PyQt6.QtCore import QObject, pyqtSignal

_LOCK = threading.Lock()
_DOWN = set()

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


def held(text, exact=True):
    if sys.platform == "win32":
        return _held_windows(text, exact)
    return _held_keys(text)


def _held_windows(text, exact=True):
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
        if exact and down(code) != (name in wanted):
            return False
        if not exact and name in wanted and not down(code):
            return False
    return True


def _remember(key, down):
    with _LOCK:
        if down:
            _DOWN.add(key)
        else:
            _DOWN.discard(key)


def _clear_down():
    with _LOCK:
        _DOWN.clear()


def _held_keys(text):
    try:
        from pynput.keyboard import HotKey
        wanted = set(HotKey.parse(_pynput_hotkey(text)))
    except Exception:
        return False
    with _LOCK:
        return bool(wanted) and wanted <= _DOWN


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
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._thread = None
        self._thread_id = 0
        self._pending = ""
        self._error = ""
        self._listener = None
        self._actions = {}
        self._armed = False

    def take(self):
        fired = self._pending
        self._pending = ""
        return fired

    def take_error(self):
        text = self._error
        self._error = ""
        return text

    def listening(self):
        # Windows reads the keys directly. Other systems need the listener's set.
        if sys.platform == "win32":
            return True
        return self._listener is not None

    def _mark(self, action):
        self._pending = action

    def start(self, record, translate=""):
        self.stop()
        bindings = []
        for action, shortcut in (("record", record), ("translate", translate)):
            shortcut = str(shortcut or "").strip()
            if not shortcut:
                continue
            if sys.platform == "win32":
                mods, key = parse_windows(shortcut)
                if key is None:
                    self.failed.emit(messages.SHORTCUT_UNREADABLE_NAMED % shortcut)
                    return False
                reason = windows_conflict(shortcut)
                if reason.startswith("Windows already uses"):
                    self.failed.emit(reason)
                    return False
                bindings.append((mods, key, shortcut, action))
            else:
                bindings.append((0, 0, shortcut, action))
        if not bindings:
            return False
        if sys.platform == "win32":
            self._thread = threading.Thread(target=self._win_loop, args=(bindings,), daemon=True)
            self._thread.start()
            return True
        return self._start_pynput(bindings)

    def stop(self):
        self._armed = False
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        _clear_down()
        if sys.platform == "win32" and self._thread_id:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.PostThreadMessageW.argtypes = [
                wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.PostThreadMessageW.restype = wintypes.BOOL
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._thread_id = 0

    def _win_loop(self, bindings):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        registered = []
        self._actions = {}
        for index, (mods, key, shortcut, action) in enumerate(bindings, start=1):
            if not user32.RegisterHotKey(None, index, mods | 0x4000, key):
                self._error = messages.SHORTCUT_TAKEN % shortcut
                for hotkey_id in registered:
                    user32.UnregisterHotKey(None, hotkey_id)
                return
            registered.append(index)
            self._actions[index] = action
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:
                    self._pending = self._actions.get(int(msg.wParam), "")
                if msg.message == 0x0012:
                    break
        finally:
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)

    def _start_pynput(self, bindings):
        try:
            from pynput import keyboard
        except ImportError:
            self.failed.emit(messages.PYNPUT_MISSING)
            return False
        combos = []
        for _mods, _key, shortcut, action in bindings:
            key_name = [part for part in parts(shortcut) if part not in WIN_MODS]
            if len(key_name) != 1:
                self.failed.emit(messages.SHORTCUT_UNREADABLE_NAMED % shortcut)
                return False
            try:
                parsed = set(keyboard.HotKey.parse(_pynput_hotkey(shortcut)))
            except Exception:
                self.failed.emit(messages.SHORTCUT_UNREADABLE_NAMED % shortcut)
                return False
            combos.append({"keys": parsed, "state": set(), "action": action, "down": False})

        def on_press(key):
            canon = self._listener.canonical(key)
            _remember(canon, True)
            if not self._armed:
                return
            for combo in combos:
                if canon in combo["keys"] and canon not in combo["state"]:
                    combo["state"].add(canon)
                    if combo["state"] == combo["keys"] and not combo["down"]:
                        combo["down"] = True
                        self._mark(combo["action"])

        def on_release(key):
            canon = self._listener.canonical(key)
            _remember(canon, False)
            for combo in combos:
                if canon in combo["state"]:
                    combo["state"].discard(canon)
                    if combo["state"] != combo["keys"]:
                        combo["down"] = False

        self._armed = True
        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.start()
        self._thread = None
        return True


def _pynput_hotkey(text):
    names = {
        "ctrl": "<ctrl>", "alt": "<alt>", "shift": "<shift>", "meta": "<cmd>",
        "esc": "<esc>", "escape": "<esc>", "space": "<space>",
    }
    bits = []
    key = ""
    for part in parts(text):
        if part in names:
            bits.append(names[part])
        elif len(part) > 1 and part[0] == "f" and part[1:].isdigit():
            key = "<%s>" % part
        else:
            key = part
    if key:
        bits.append(key)
    return "+".join(bits)
