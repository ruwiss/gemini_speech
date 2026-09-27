import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave

from . import messages
from . import paths

PORT = 4982
URL = "http://127.0.0.1:%s" % PORT


def healthy():
    try:
        with urllib.request.urlopen(URL + "/health", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def cookies_known():
    if not os.path.exists(paths.cookies_path()):
        return False
    text = open(paths.cookies_path(), encoding="utf-8").read()
    return "SAPISID=" in text and "__Secure-1PSID=" in text


def cookies_ready():
    if not cookies_known():
        return False
    return time.time() - os.path.getmtime(paths.cookies_path()) <= 3600


class Server:
    def __init__(self):
        self.proc = None
        self._job = None
        self._logs = []
        self._stopped = False

    def start(self):
        self._stopped = False
        if healthy():
            return
        env = os.environ.copy()
        env["BROWSER_COOKIES"] = paths.cookies_path()
        env["PORT"] = str(PORT)
        env["GEMINI_SPEECH_PARENT"] = str(os.getpid())
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            self._job = _win_job()
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--server"]
            cwd = paths.ROOT
        else:
            cmd = [sys.executable, "-u", paths.SERVER]
            cwd = os.path.dirname(paths.SERVER)
        out = open(paths.log_path(), "a", encoding="utf-8")
        err = open(paths.err_path(), "a", encoding="utf-8")
        self._logs = [out, err]
        self.proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=out,
            stderr=err,
            **kwargs,
        )
        open(paths.pid_path(), "w", encoding="utf-8").write(str(self.proc.pid))
        if sys.platform == "win32":
            _win_assign(self._job, self.proc.pid)
        for _ in range(20):
            if healthy():
                return
            time.sleep(0.15)
        raise RuntimeError(messages.SERVER_NOT_STARTED)

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        pids = set(listeners(PORT))
        if self.proc is not None and self.proc.poll() is None:
            pids.add(self.proc.pid)
        pid_file = paths.pid_path()
        if os.path.exists(pid_file):
            try:
                pids.add(int(open(pid_file, encoding="utf-8").read().strip()))
            except ValueError:
                pass
        for pid in pids:
            _kill(pid)
        if self.proc is not None:
            try:
                self.proc.wait(timeout=3)
            except Exception:
                pass
        self.proc = None
        self._job = None
        for handle in self._logs:
            handle.close()
        self._logs = []
        try:
            os.remove(pid_file)
        except OSError:
            pass


def listeners(port):
    needle = ":%d" % port
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "tcp"], text=True, errors="replace", timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            return set()
        found = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0] != "TCP" or parts[3] != "LISTENING":
                continue
            if parts[1].endswith(needle) and parts[-1].isdigit():
                found.add(int(parts[-1]))
        return found
    try:
        out = subprocess.check_output(
            ["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"],
            text=True, errors="replace", timeout=8,
        )
    except Exception:
        return set()
    return {int(line) for line in out.split() if line.isdigit()}


def _kill(pid):
    if not pid or pid == os.getpid():
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return
    try:
        os.kill(pid, 15)
    except OSError:
        pass


def _win_job():
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class Counters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", Basic),
            ("IoInfo", Counters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None
    info = Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000
    ok = kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
    if not ok:
        kernel32.CloseHandle(handle)
        return None
    return handle


def _win_assign(job, pid):
    if not job:
        return
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    process = kernel32.OpenProcess(0x0100 | 0x0001, False, pid)
    if not process:
        return
    kernel32.AssignProcessToJobObject(job, process)
    kernel32.CloseHandle(process)


def _error_text(detail):
    detail = (detail or "").strip()
    if detail.startswith("{"):
        try:
            message = json.loads(detail)["error"]["message"]
        except Exception:
            message = ""
        if isinstance(message, str) and message.strip():
            return message.strip()[:240]
    return detail[:240]


def _json(method, path, body=None, timeout=20, content_type=None):
    headers = {}
    data = body
    if isinstance(body, str):
        data = body.encode()
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(
        URL + path, data=data, headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(_error_text(detail)) from exc


def live_start():
    return _json("POST", "/v1/live", b"{}", timeout=20, content_type="application/json")["id"]


def live_write(sid, pcm):
    if not pcm:
        return
    _json("POST", "/v1/live/" + sid, pcm, timeout=8, content_type="application/octet-stream")


def live_finish(sid):
    text = (_json("POST", "/v1/live/" + sid + "/finish", b"", timeout=30).get("text") or "").strip()
    if not text:
        raise RuntimeError(messages.NO_SPEECH_RECOGNIZED)
    return text


def live_cancel(sid):
    if not sid:
        return
    try:
        _json("POST", "/v1/live/" + sid + "/cancel", b"", timeout=5)
    except Exception:
        pass


def transcribe(pcm):
    if len(pcm) < 1600:
        raise RuntimeError(messages.RECORDING_TOO_SHORT)
    path = os.path.join(paths.config_dir(), "take.wav")
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(pcm)
    boundary = "geminispeech"
    body = b"".join([
        b"--%s\r\n" % boundary.encode(),
        b'Content-Disposition: form-data; name="file"; filename="take.wav"\r\n',
        b"Content-Type: audio/wav\r\n\r\n",
        open(path, "rb").read(),
        b"\r\n--%s--\r\n" % boundary.encode(),
    ])
    req = urllib.request.Request(
        URL + "/v1/audio/transcriptions",
        data=body,
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(_error_text(detail)) from exc
    text = (payload.get("text") or "").strip()
    if not text:
        raise RuntimeError(messages.EMPTY_TRANSCRIPT)
    return text
