import faulthandler
import os
import sys

_HANDLE = None
_FILTER = None


def install():
    global _HANDLE
    if _HANDLE is not None:
        return
    try:
        from .paths import log_dir
        path = os.path.join(log_dir(), "crash.log")
        _HANDLE = open(path, "a", encoding="utf-8", errors="replace")
    except Exception:
        return
    _HANDLE.write("\n--- pid %s frozen %s ---\n" % (os.getpid(), getattr(sys, "frozen", False)))
    _HANDLE.flush()
    faulthandler.enable(_HANDLE, all_threads=True)
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        import traceback
        _HANDLE.write("exception\n")
        traceback.print_exception(exc_type, exc, tb, file=_HANDLE)
        _HANDLE.flush()
        previous(exc_type, exc, tb)

    sys.excepthook = hook
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        try:
            _guard_native(_HANDLE)
        except Exception:
            import traceback
            traceback.print_exc(file=_HANDLE)
            _HANDLE.flush()


def note(text):
    if _HANDLE is None:
        return
    _HANDLE.write(text.rstrip() + "\n")
    _HANDLE.flush()


def _guard_native(handle):
    import ctypes
    from ctypes import wintypes

    class Record(ctypes.Structure):
        _fields_ = [
            ("ExceptionCode", wintypes.DWORD),
            ("ExceptionFlags", wintypes.DWORD),
            ("ExceptionRecord", ctypes.c_void_p),
            ("ExceptionAddress", ctypes.c_void_p),
            ("NumberParameters", wintypes.DWORD),
            ("unused", wintypes.DWORD),
        ]

    class Pointers(ctypes.Structure):
        _fields_ = [
            ("ExceptionRecord", ctypes.POINTER(Record)),
            ("ContextRecord", ctypes.c_void_p),
        ]

    handler_type = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.POINTER(Pointers))

    def on_crash(info):
        try:
            record = info.contents.ExceptionRecord.contents
            handle.write("native 0x%08x at %s\n" % (record.ExceptionCode & 0xFFFFFFFF, record.ExceptionAddress))
            handle.flush()
            faulthandler.dump_traceback(handle, all_threads=True)
            handle.flush()
        except Exception:
            pass
        return 1

    global _FILTER
    _FILTER = handler_type(on_crash)
    ctypes.windll.kernel32.SetUnhandledExceptionFilter(_FILTER)
