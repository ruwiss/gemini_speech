import ctypes
import json
import os
import socket
import subprocess
import sys
import time

from .crashlog import note

OVERLAY_TITLE = "GeminiSpeechAPI-indicator"
_SCRIPT = "gemini_speech_follow"
_KWIN = False
_HYPR = ""
_FOCUS = ""
_ADDR = ""
_UINPUT = None
_BUS = None
_PORTAL_READY = False
_PORTAL_FAILED = False
_SESSION = ""


def wayland():
    if sys.platform != "linux":
        return False
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def start():
    global _KWIN, _HYPR
    if sys.platform != "linux":
        return
    if wayland() and _kwin_load():
        _KWIN = True
        note("overlay follow: kwin")
        return
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or ""
    if sig and _hypr_socket():
        _HYPR = sig
        _hypr_rules()
        note("overlay follow: hyprland")


def stop():
    global _KWIN, _UINPUT, _PORTAL_READY, _SESSION
    if _KWIN:
        _kwin_unload()
        _KWIN = False
    if _UINPUT is not None:
        try:
            os.close(_UINPUT)
        except OSError:
            pass
        _UINPUT = None
    _PORTAL_READY = False
    _SESSION = ""
    if _BUS is not None:
        _BUS.close()


def overlay_hidden():
    global _ADDR
    _ADDR = ""


def follows():
    return _KWIN or bool(_HYPR)


def place(widget):
    if _KWIN:
        return True
    if not _HYPR:
        return False
    pos = _hypr_cursor()
    if pos is None:
        return False
    addr = _overlay_address()
    if not addr:
        return False
    x = pos[0] + 8
    y = pos[1] - widget.height() // 2
    area = _hypr_area(pos)
    if area is not None:
        x = max(area[0], min(x, area[0] + area[2] - widget.width()))
        y = max(area[1], min(y, area[1] + area[3] - widget.height()))
    _hypr("dispatch movewindowpixel exact %d %d,address:%s" % (x, y, addr))
    return True


def remember_focus():
    global _FOCUS
    if not _HYPR:
        _FOCUS = ""
        return
    data = _hypr_json("activewindow")
    title = (data or {}).get("title") or ""
    if OVERLAY_TITLE in title:
        return
    _FOCUS = (data or {}).get("address") or ""


def paste(text):
    if not _copy(text):
        return False
    _restore_focus()
    if _uinput_paste():
        note("paste uinput")
        return True
    if _tool_paste():
        return True
    if _portal_paste():
        note("paste portal")
        return True
    if not wayland() and _xtest_paste():
        note("paste xtest")
        return True
    note("paste failed")
    return False


def _copy(text):
    copied = False
    try:
        from PyQt6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(text)
        app = QGuiApplication.instance()
        if app is not None:
            app.processEvents()
        copied = True
    except Exception:
        pass
    if _wl_copy(text):
        copied = True
    if _klipper(text):
        copied = True
    return copied


def _restore_focus():
    if _FOCUS:
        _hypr("dispatch focuswindow address:%s" % _FOCUS)
        return
    if _KWIN:
        _kwin_focus_at_cursor()


def _runtime():
    return os.environ.get("XDG_RUNTIME_DIR") or ("/run/user/%d" % os.getuid())


def _run(cmd, timeout=2):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _dbus_send(path, interface, method, *args):
    cmd = [
        "dbus-send", "--session", "--print-reply",
        "--dest=org.kde.KWin", path, "%s.%s" % (interface, method),
    ]
    cmd.extend(args)
    return _run(cmd, 5)


def _kwin_load():
    runtime = _runtime()
    path = os.path.join(runtime, "gemini-speech-follow.js")
    try:
        os.makedirs(runtime, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(_kwin_script())
    except OSError:
        return False
    _kwin_unload()
    reply = _dbus_send(
        "/Scripting", "org.kde.kwin.Scripting", "loadScript",
        "string:%s" % path, "string:%s" % _SCRIPT,
    )
    if reply is None or reply.returncode != 0:
        return False
    script_id = None
    for line in reply.stdout.splitlines():
        line = line.strip()
        if line.startswith("int32 "):
            try:
                script_id = int(line.split()[-1])
            except ValueError:
                script_id = None
    if script_id is None or script_id < 0:
        return False
    ran = _dbus_send(
        "/Scripting/Script%d" % script_id, "org.kde.kwin.Script", "run",
    )
    return ran is not None and ran.returncode == 0


def _kwin_focus_at_cursor():
    body = """
var pos = workspace.cursorPos;
var list = workspace.windowAt(pos, 8);
for (var i = 0; i < list.length; i++) {
    var w = list[i];
    if (!w || w.pid === %d) continue;
    var cls = (w.resourceClass || "") + " " + (w.resourceName || "");
    if (cls.indexOf("portal") >= 0) continue;
    workspace.activeWindow = w;
    break;
}
""" % os.getpid()
    _kwin_once("gemini_speech_focus", body)


def _kwin_once(name, body):
    runtime = _runtime()
    path = os.path.join(runtime, name + ".js")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
    except OSError:
        return False
    _dbus_send("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "string:%s" % name)
    reply = _dbus_send(
        "/Scripting", "org.kde.kwin.Scripting", "loadScript",
        "string:%s" % path, "string:%s" % name,
    )
    if reply is None or reply.returncode != 0:
        return False
    script_id = None
    for line in reply.stdout.splitlines():
        line = line.strip()
        if line.startswith("int32 "):
            try:
                script_id = int(line.split()[-1])
            except ValueError:
                script_id = None
    if script_id is None or script_id < 0:
        return False
    ran = _dbus_send("/Scripting/Script%d" % script_id, "org.kde.kwin.Script", "run")
    _dbus_send("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "string:%s" % name)
    return ran is not None and ran.returncode == 0


def _kwin_unload():
    _dbus_send(
        "/Scripting", "org.kde.kwin.Scripting", "unloadScript",
        "string:%s" % _SCRIPT,
    )


def _kwin_script():
    return """
var TITLE = %s;
var PID = %d;
var previous = null;
var placed = false;

function windows() {
    try {
        if (workspace.windowList) return workspace.windowList();
    } catch (e) {}
    return workspace.stackingOrder;
}

function ours(w) {
    return w && w.pid === PID && w.caption && w.caption.indexOf(TITLE) >= 0;
}

function ignored(w) {
    if (!w || ours(w)) return true;
    var cls = (w.resourceClass || "") + " " + (w.resourceName || "");
    var cap = w.caption || "";
    if (cls.indexOf("portal") >= 0 || cls.indexOf("polkit") >= 0) return true;
    if (cap.indexOf("Remote") >= 0) return true;
    return false;
}

function remember() {
    var active = workspace.activeWindow;
    if (!ignored(active)) previous = active;
}

function place() {
    try {
        remember();
        var pos = workspace.cursorPos;
        var list = windows();
        for (var i = 0; i < list.length; i++) {
            var w = list[i];
            if (!ours(w) || w.deleted) continue;
            var x = Math.round(pos.x + 8);
            var y = Math.round(pos.y - w.height / 2);
            var screen = workspace.screenAt(pos);
            if (screen) {
                var g = screen.geometry;
                x = Math.max(g.x, Math.min(x, g.x + g.width - w.width));
                y = Math.max(g.y, Math.min(y, g.y + g.height - w.height));
            }
            if (!placed) {
                w.keepAbove = true;
                w.skipTaskbar = true;
                w.skipPager = true;
                w.skipSwitcher = true;
                w.onAllDesktops = true;
                placed = true;
            }
            if (Math.abs(w.x - x) < 1 && Math.abs(w.y - y) < 1) continue;
            var q = Object.assign({}, w.frameGeometry);
            q.x = x;
            q.y = y;
            w.frameGeometry = q;
        }
    } catch (e) {}
}

var restoring = false;
function onActivated(w) {
    if (restoring) return;
    if (!ours(w)) {
        if (!ignored(w)) previous = w;
        return;
    }
    if (!previous) return;
    restoring = true;
    workspace.activeWindow = previous;
    restoring = false;
}

remember();
workspace.cursorPosChanged.connect(place);
workspace.windowActivated.connect(onActivated);
workspace.windowAdded.connect(function(w) {
    if (ours(w)) place();
});
place();
""" % (json.dumps(OVERLAY_TITLE), os.getpid())


def _hypr_socket():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or _HYPR
    if not sig:
        return ""
    path = os.path.join(_runtime(), "hypr", sig, ".socket.sock")
    return path if os.path.exists(path) else ""


def _hypr(command, json_out=False):
    path = _hypr_socket()
    if not path:
        return ""
    payload = ("j/" if json_out else "/") + command
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.25)
        sock.connect(path)
        sock.sendall(payload.encode())
        chunks = []
        while True:
            try:
                data = sock.recv(65536)
            except TimeoutError:
                break
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
            if len(data) < 65536:
                break
        sock.close()
    except OSError:
        return ""
    return b"".join(chunks).decode("utf-8", "replace")


def _hypr_json(command):
    raw = _hypr(command, True).strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _hypr_rules():
    title = "title:^(GeminiSpeechAPI-indicator)$"
    for rule in ("float", "nofocus", "noinitialfocus", "noborder", "pin"):
        _hypr("keyword windowrulev2 %s,%s" % (rule, title))


def _hypr_cursor():
    raw = _hypr("cursorpos").strip().replace(",", " ")
    parts = raw.split()
    if len(parts) < 2:
        return None
    try:
        return int(float(parts[0])), int(float(parts[1]))
    except ValueError:
        return None


_AREAS = None


def _hypr_area(pos):
    global _AREAS
    if _AREAS is None:
        data = _hypr_json("monitors") or []
        areas = []
        for mon in data:
            try:
                areas.append((int(mon["x"]), int(mon["y"]), int(mon["width"]), int(mon["height"])))
            except (KeyError, TypeError, ValueError):
                continue
        _AREAS = areas
    for area in _AREAS:
        if area[0] <= pos[0] < area[0] + area[2] and area[1] <= pos[1] < area[1] + area[3]:
            return area
    return _AREAS[0] if _AREAS else None


def _overlay_address():
    global _ADDR
    if _ADDR:
        return _ADDR
    clients = _hypr_json("clients") or []
    pid = os.getpid()
    for client in clients:
        title = client.get("title") or ""
        if client.get("pid") != pid or OVERLAY_TITLE not in title:
            continue
        _ADDR = client.get("address") or ""
        if _ADDR and not client.get("floating"):
            _hypr("dispatch togglefloating address:%s" % _ADDR)
        return _ADDR
    return ""


def _klipper(text):
    bus = _bus()
    if bus is None or not bus.open():
        return False
    for dest, path, iface in (
        ("org.kde.klipper", "/klipper", "org.kde.klipper.klipper"),
        ("org.kde.plasmashell", "/org/kde/klipper", "org.kde.klipper.klipper"),
    ):
        reply = bus.call(dest, path, iface, "setClipboardContents", [("s", text)], 1500)
        if reply is not None:
            bus.unref(reply)
            return True
    return False


def _wl_copy(text):
    if not wayland():
        return False
    try:
        proc = subprocess.run(["wl-copy"], input=text.encode(), timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _tool_paste():
    commands = (
        ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
        ["wtype", "-M", "ctrl", "v", "-m", "ctrl"],
        ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
    )
    for cmd in commands:
        proc = _run(cmd)
        if proc is not None and proc.returncode == 0:
            note("paste %s" % cmd[0])
            return True
    try:
        proc = subprocess.run(["dotool"], input=b"key ctrl+v\n", timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    if proc is not None and proc.returncode == 0:
        note("paste dotool")
        return True
    return False


def _ioc(direction, nr, size):
    return (direction << 30) | (size << 16) | (ord("U") << 8) | nr


class _InputId(ctypes.Structure):
    _fields_ = [
        ("bustype", ctypes.c_uint16),
        ("vendor", ctypes.c_uint16),
        ("product", ctypes.c_uint16),
        ("version", ctypes.c_uint16),
    ]


class _USetup(ctypes.Structure):
    _fields_ = [
        ("id", _InputId),
        ("name", ctypes.c_char * 80),
        ("ff_effects_max", ctypes.c_uint32),
    ]


class _Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


class _Event(ctypes.Structure):
    _fields_ = [
        ("time", _Timeval),
        ("type", ctypes.c_uint16),
        ("code", ctypes.c_uint16),
        ("value", ctypes.c_int32),
    ]


def _uinput_open():
    global _UINPUT
    if _UINPUT is not None:
        return _UINPUT
    try:
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return None
    libc = ctypes.CDLL(None, use_errno=True)

    def ioctl(request, arg=0):
        if isinstance(arg, int):
            result = libc.ioctl(fd, ctypes.c_ulong(request), ctypes.c_ulong(arg))
        else:
            result = libc.ioctl(fd, ctypes.c_ulong(request), arg)
        if result < 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))

    try:
        ioctl(_ioc(1, 100, 4), 1)
        ioctl(_ioc(1, 101, 4), 29)
        ioctl(_ioc(1, 101, 4), 47)
        setup = _USetup()
        setup.id.bustype = 0x03
        setup.name = b"GeminiSpeechAPI"
        ioctl(_ioc(1, 3, ctypes.sizeof(setup)), ctypes.byref(setup))
        ioctl(_ioc(0, 1, 0))
    except OSError:
        os.close(fd)
        return None
    time.sleep(0.12)
    _UINPUT = fd
    return fd


def _emit(fd, etype, code, value):
    ev = _Event()
    ev.type = etype
    ev.code = code
    ev.value = value
    os.write(fd, bytes(ev))


def _uinput_paste():
    fd = _uinput_open()
    if fd is None:
        return False
    try:
        for code, value in ((29, 1), (47, 1), (47, 0), (29, 0)):
            _emit(fd, 1, code, value)
            _emit(fd, 0, 0, 0)
    except OSError:
        return False
    return True


def _xtest_paste():
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        xtst = ctypes.CDLL("libXtst.so.6")
    except OSError:
        return False
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XKeysymToKeycode.restype = ctypes.c_uint
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeKeyEvent.restype = ctypes.c_int
    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    display = x11.XOpenDisplay(None)
    if not display:
        return False
    try:
        ctrl = x11.XKeysymToKeycode(display, 0xffe3)
        key = x11.XKeysymToKeycode(display, 0x76)
        if not ctrl or not key:
            return False
        xtst.XTestFakeKeyEvent(display, ctrl, 1, 0)
        xtst.XTestFakeKeyEvent(display, key, 1, 0)
        xtst.XTestFakeKeyEvent(display, key, 0, 0)
        xtst.XTestFakeKeyEvent(display, ctrl, 0, 0)
        x11.XFlush(display)
    finally:
        x11.XCloseDisplay(display)
    return True


class _Iter(ctypes.Structure):
    _fields_ = [("pad", ctypes.c_byte * 256)]


class _Bus:
    def __init__(self):
        self.lib = None
        self.conn = None
        self.unique = ""
        self._keep = []

    def open(self):
        if self.conn:
            return True
        addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        if not addr:
            return False
        lib = None
        for name in ("libdbus-1.so.3", "libdbus-1.so"):
            try:
                lib = ctypes.CDLL(name)
                break
            except OSError:
                continue
        if lib is None:
            return False
        self.lib = lib
        lib.dbus_threads_init_default.restype = None
        lib.dbus_threads_init_default.argtypes = []
        lib.dbus_error_init.argtypes = [ctypes.c_void_p]
        lib.dbus_error_free.argtypes = [ctypes.c_void_p]
        lib.dbus_error_is_set.restype = ctypes.c_uint32
        lib.dbus_error_is_set.argtypes = [ctypes.c_void_p]
        lib.dbus_connection_open_private.restype = ctypes.c_void_p
        lib.dbus_connection_open_private.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
        lib.dbus_bus_register.restype = ctypes.c_uint32
        lib.dbus_bus_register.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.dbus_bus_get_unique_name.restype = ctypes.c_char_p
        lib.dbus_bus_get_unique_name.argtypes = [ctypes.c_void_p]
        lib.dbus_bus_add_match.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]
        lib.dbus_connection_flush.argtypes = [ctypes.c_void_p]
        lib.dbus_connection_read_write.restype = ctypes.c_uint32
        lib.dbus_connection_read_write.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.dbus_connection_pop_message.restype = ctypes.c_void_p
        lib.dbus_connection_pop_message.argtypes = [ctypes.c_void_p]
        lib.dbus_connection_close.argtypes = [ctypes.c_void_p]
        lib.dbus_connection_unref.argtypes = [ctypes.c_void_p]
        lib.dbus_message_new_method_call.restype = ctypes.c_void_p
        lib.dbus_message_new_method_call.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.dbus_message_unref.argtypes = [ctypes.c_void_p]
        lib.dbus_message_iter_init_append.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.dbus_message_iter_init.restype = ctypes.c_uint32
        lib.dbus_message_iter_init.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.dbus_message_iter_append_basic.restype = ctypes.c_uint32
        lib.dbus_message_iter_append_basic.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.dbus_message_iter_open_container.restype = ctypes.c_uint32
        lib.dbus_message_iter_open_container.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p]
        lib.dbus_message_iter_close_container.restype = ctypes.c_uint32
        lib.dbus_message_iter_close_container.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.dbus_message_iter_get_arg_type.restype = ctypes.c_int
        lib.dbus_message_iter_get_arg_type.argtypes = [ctypes.c_void_p]
        lib.dbus_message_iter_get_basic.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.dbus_message_iter_next.restype = ctypes.c_uint32
        lib.dbus_message_iter_next.argtypes = [ctypes.c_void_p]
        lib.dbus_message_iter_recurse.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.dbus_message_get_type.restype = ctypes.c_int
        lib.dbus_message_get_type.argtypes = [ctypes.c_void_p]
        lib.dbus_message_get_path.restype = ctypes.c_char_p
        lib.dbus_message_get_path.argtypes = [ctypes.c_void_p]
        lib.dbus_message_get_member.restype = ctypes.c_char_p
        lib.dbus_message_get_member.argtypes = [ctypes.c_void_p]
        lib.dbus_connection_send_with_reply_and_block.restype = ctypes.c_void_p
        lib.dbus_connection_send_with_reply_and_block.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.dbus_threads_init_default()
        err = self._err()
        conn = lib.dbus_connection_open_private(addr.encode(), err)
        if not conn or lib.dbus_error_is_set(err):
            self._clear(err)
            return False
        if not lib.dbus_bus_register(conn, err):
            self._clear(err)
            lib.dbus_connection_close(conn)
            lib.dbus_connection_unref(conn)
            return False
        self._clear(err)
        self.conn = conn
        name = lib.dbus_bus_get_unique_name(conn)
        self.unique = name.decode() if name else ""
        err = self._err()
        lib.dbus_bus_add_match(
            conn,
            b"type='signal',interface='org.freedesktop.portal.Request',member='Response'",
            err,
        )
        self._clear(err)
        lib.dbus_connection_flush(conn)
        return True

    def close(self):
        if not self.conn or not self.lib:
            return
        self.lib.dbus_connection_close(self.conn)
        self.lib.dbus_connection_unref(self.conn)
        self.conn = None

    def sender_id(self):
        return self.unique[1:].replace(".", "_") if self.unique.startswith(":") else ""

    def call(self, dest, path, iface, method, items, timeout=8000):
        if not self.conn:
            return None
        lib = self.lib
        self._keep = []
        msg = lib.dbus_message_new_method_call(dest.encode(), path.encode(), iface.encode(), method.encode())
        if not msg:
            return None
        it = _Iter()
        lib.dbus_message_iter_init_append(msg, ctypes.byref(it))
        for kind, value in items:
            self._append(it, kind, value)
        err = self._err()
        reply = lib.dbus_connection_send_with_reply_and_block(self.conn, msg, timeout, err)
        failed = (not reply) or bool(lib.dbus_error_is_set(err))
        self._clear(err)
        lib.dbus_message_unref(msg)
        self._keep = []
        if failed:
            if reply:
                lib.dbus_message_unref(reply)
            return None
        return reply

    def unref(self, msg):
        if msg and self.lib:
            self.lib.dbus_message_unref(msg)

    def object_path(self, msg):
        if not msg:
            return ""
        it = _Iter()
        if not self.lib.dbus_message_iter_init(msg, ctypes.byref(it)):
            return ""
        if self.lib.dbus_message_iter_get_arg_type(ctypes.byref(it)) != ord("o"):
            return ""
        return self._basic(it, ord("o"))

    def wait_response(self, path, timeout_ms):
        from PyQt6.QtWidgets import QApplication
        lib = self.lib
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            lib.dbus_connection_read_write(self.conn, 40)
            while True:
                msg = lib.dbus_connection_pop_message(self.conn)
                if not msg:
                    break
                try:
                    member = lib.dbus_message_get_member(msg)
                    mpath = lib.dbus_message_get_path(msg)
                    if lib.dbus_message_get_type(msg) == 4 and member and mpath:
                        if member.decode() == "Response" and mpath.decode() == path:
                            return self._response(msg)
                finally:
                    lib.dbus_message_unref(msg)
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
        return None, {}

    def _err(self):
        buf = (ctypes.c_byte * 128)()
        self.lib.dbus_error_init(buf)
        return buf

    def _clear(self, err):
        if self.lib.dbus_error_is_set(err):
            self.lib.dbus_error_free(err)

    def _append(self, it, kind, value):
        lib = self.lib
        if kind in ("s", "o"):
            held = ctypes.c_char_p(value.encode())
            self._keep.append(held)
            lib.dbus_message_iter_append_basic(ctypes.byref(it), ord(kind), ctypes.byref(held))
            return
        if kind == "u":
            held = ctypes.c_uint32(int(value))
            self._keep.append(held)
            lib.dbus_message_iter_append_basic(ctypes.byref(it), ord("u"), ctypes.byref(held))
            return
        if kind == "i":
            held = ctypes.c_int32(int(value))
            self._keep.append(held)
            lib.dbus_message_iter_append_basic(ctypes.byref(it), ord("i"), ctypes.byref(held))
            return
        if kind != "a{sv}":
            return
        arr = _Iter()
        sig = ctypes.c_char_p(b"{sv}")
        self._keep.append(sig)
        lib.dbus_message_iter_open_container(ctypes.byref(it), ord("a"), sig, ctypes.byref(arr))
        for key, item in value.items():
            entry = _Iter()
            lib.dbus_message_iter_open_container(ctypes.byref(arr), ord("e"), None, ctypes.byref(entry))
            self._append(entry, "s", key)
            var = _Iter()
            vsig = ctypes.c_char_p(item[0].encode())
            self._keep.append(vsig)
            lib.dbus_message_iter_open_container(ctypes.byref(entry), ord("v"), vsig, ctypes.byref(var))
            self._append(var, item[0], item[1])
            lib.dbus_message_iter_close_container(ctypes.byref(entry), ctypes.byref(var))
            lib.dbus_message_iter_close_container(ctypes.byref(arr), ctypes.byref(entry))
        lib.dbus_message_iter_close_container(ctypes.byref(it), ctypes.byref(arr))

    def _basic(self, it, kind):
        if kind in (ord("s"), ord("o")):
            ptr = ctypes.c_char_p()
            self.lib.dbus_message_iter_get_basic(ctypes.byref(it), ctypes.byref(ptr))
            return ptr.value.decode() if ptr.value else ""
        if kind in (ord("u"), ord("i")):
            num = ctypes.c_uint32()
            self.lib.dbus_message_iter_get_basic(ctypes.byref(it), ctypes.byref(num))
            return int(num.value)
        return None

    def _response(self, msg):
        it = _Iter()
        if not self.lib.dbus_message_iter_init(msg, ctypes.byref(it)):
            return None, {}
        code = self._basic(it, ord("u"))
        fields = {}
        if self.lib.dbus_message_iter_next(ctypes.byref(it)):
            fields = self._fields(it)
        return code, fields

    def _fields(self, array_iter):
        found = {}
        if self.lib.dbus_message_iter_get_arg_type(ctypes.byref(array_iter)) != ord("a"):
            return found
        elem = _Iter()
        self.lib.dbus_message_iter_recurse(ctypes.byref(array_iter), ctypes.byref(elem))
        while self.lib.dbus_message_iter_get_arg_type(ctypes.byref(elem)) != 0:
            entry = _Iter()
            self.lib.dbus_message_iter_recurse(ctypes.byref(elem), ctypes.byref(entry))
            key = self._basic(entry, ord("s"))
            self.lib.dbus_message_iter_next(ctypes.byref(entry))
            var = _Iter()
            self.lib.dbus_message_iter_recurse(ctypes.byref(entry), ctypes.byref(var))
            kind = self.lib.dbus_message_iter_get_arg_type(ctypes.byref(var))
            if key and kind in (ord("s"), ord("o")):
                found[key] = self._basic(var, kind) or ""
            self.lib.dbus_message_iter_next(ctypes.byref(elem))
        return found


def _bus():
    global _BUS
    if _BUS is None:
        _BUS = _Bus()
    return _BUS


def _token_path():
    from .paths import config_dir
    return os.path.join(config_dir(), "portal-token")


def _load_token():
    try:
        return open(_token_path(), encoding="utf-8").read().strip()
    except OSError:
        return ""


def _save_token(token):
    if not token:
        return
    try:
        with open(_token_path(), "w", encoding="utf-8") as handle:
            handle.write(token)
    except OSError:
        pass


def _portal_request(bus, method, items):
    reply = bus.call(
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.RemoteDesktop",
        method,
        items,
    )
    if reply is None:
        return ""
    path = bus.object_path(reply)
    bus.unref(reply)
    return path


def _portal_paste():
    global _PORTAL_READY, _PORTAL_FAILED, _SESSION
    if not wayland():
        return False
    if _PORTAL_FAILED:
        return False
    bus = _bus()
    if not _PORTAL_READY:
        if not bus.open():
            _PORTAL_FAILED = True
            return False
        sid = bus.sender_id()
        if not sid:
            _PORTAL_FAILED = True
            return False
        session_token = "gemini_speech_%d" % os.getpid()
        _SESSION = "/org/freedesktop/portal/desktop/session/%s/%s" % (sid, session_token)
        created = _portal_request(bus, "CreateSession", [(
            "a{sv}", {
                "handle_token": ("s", "gemini_create_%d" % os.getpid()),
                "session_handle_token": ("s", session_token),
            },
        )])
        code, fields = bus.wait_response(created, 5000) if created else (None, {})
        if code != 0:
            note("portal session failed")
            _PORTAL_FAILED = True
            return False
        if fields.get("session_handle"):
            _SESSION = fields["session_handle"]
        options = {"types": ("u", 1), "persist_mode": ("u", 2)}
        saved = _load_token()
        if saved:
            options["restore_token"] = ("s", saved)
        selected = _portal_request(bus, "SelectDevices", [
            ("o", _SESSION),
            ("a{sv}", options),
        ])
        code, _fields = bus.wait_response(selected, 5000) if selected else (None, {})
        if code != 0:
            note("portal devices failed")
            _PORTAL_FAILED = True
            return False
        started = _portal_request(bus, "Start", [
            ("o", _SESSION),
            ("s", ""),
            ("a{sv}", {}),
        ])
        code, fields = bus.wait_response(started, 45000) if started else (None, {})
        if code != 0:
            note("portal start failed")
            _PORTAL_FAILED = True
            return False
        _save_token(fields.get("restore_token") or "")
        _PORTAL_READY = True
        _restore_focus()
    for code, state in ((29, 1), (47, 1), (47, 0), (29, 0)):
        reply = bus.call(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.RemoteDesktop",
            "NotifyKeyboardKeycode",
            [("o", _SESSION), ("a{sv}", {}), ("i", code), ("u", state)],
            2000,
        )
        if reply is None:
            return False
        bus.unref(reply)
    return True
