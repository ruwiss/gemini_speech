import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request

from . import __version__

REPO = "ruwiss/gemini_speech"
API = "https://api.github.com/repos/%s/releases/latest" % REPO
ASSETS = {
    "win32": "GeminiSpeechAPI-Setup.exe",
    "darwin": "GeminiSpeechAPI-macos.dmg",
    "linux": "GeminiSpeechAPI-linux.tar.gz",
}
MIN_SIZE = 1000000


def _log(text):
    try:
        from .crashlog import note
        note("update: " + text)
    except Exception:
        pass


def _ssl_context():
    cafile = os.environ.get("SSL_CERT_FILE") or ""
    if cafile and os.path.isfile(cafile):
        return ssl.create_default_context(cafile=cafile)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _workdir():
    path = os.path.join(tempfile.gettempdir(), "GeminiSpeechAPI-update")
    os.makedirs(path, exist_ok=True)
    return path


def check():
    if not getattr(sys, "frozen", False):
        return None
    name = ASSETS.get("linux" if sys.platform.startswith("linux") else sys.platform)
    if not name:
        return None
    remote = _latest()
    if not remote or not _newer(remote["tag"], __version__):
        _log("up to date (local %s, remote %s)" % (__version__, remote and remote["tag"]))
        return None
    asset = next((item for item in remote["assets"] if item["name"] == name), None)
    if not asset or not asset["url"]:
        _log("release %s has no %s asset" % (remote["tag"], name))
        return None
    return {"version": remote["tag"].lstrip("vV"), "name": name, "url": asset["url"], "digest": asset["digest"]}


def download(info):
    target = os.path.join(_workdir(), info["name"])
    part = target + ".part"
    request = urllib.request.Request(info["url"], headers={"User-Agent": "GeminiSpeechAPI"})
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=60, context=_ssl_context()) as response, open(part, "wb") as out:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    expected = info["digest"]
    if size < MIN_SIZE:
        os.remove(part)
        raise RuntimeError("download too small: %d bytes" % size)
    if expected and digest.hexdigest() != expected:
        os.remove(part)
        raise RuntimeError("checksum mismatch")
    os.replace(part, target)
    _log("downloaded %s (%d bytes)" % (target, size))
    return target


def launch(path):
    if sys.platform == "win32":
        return _launch_windows(path)
    if sys.platform == "darwin":
        subprocess.Popen(["open", path], close_fds=True)
        return True
    return _launch_linux(path)


def _launch_windows(path):
    log = os.path.join(_workdir(), "setup.log")
    flags = 0x00000008 | 0x00000200
    try:
        subprocess.Popen(
            [path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/LOG=" + log],
            close_fds=True,
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        _log("installer start failed: %s" % exc)
        return False
    _log("installer started")
    return True


def _launch_linux(path):
    folder = os.path.dirname(sys.executable)
    script = os.path.join(_workdir(), "update.sh")
    log = os.path.join(_workdir(), "update.log")
    open(script, "w", encoding="utf-8").write(
        "#!/bin/sh\n"
        "exec >%s 2>&1\n"
        "while kill -0 %d 2>/dev/null; do sleep 0.2; done\n"
        "tar -xzf %s -C %s || exit 1\n"
        "exec %s\n" % (_quote(log), os.getpid(), _quote(path), _quote(os.path.dirname(folder)), _quote(sys.executable))
    )
    os.chmod(script, 0o755)
    try:
        subprocess.Popen(["/bin/sh", script], start_new_session=True, close_fds=True)
    except Exception as exc:
        _log("updater start failed: %s" % exc)
        return False
    return True


def _latest():
    request = urllib.request.Request(
        API,
        headers={"User-Agent": "GeminiSpeechAPI", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=20, context=_ssl_context()) as response:
        body = json.loads(response.read().decode("utf-8"))
    assets = []
    for item in body.get("assets") or []:
        digest = item.get("digest") or ""
        assets.append({
            "name": item.get("name") or "",
            "url": item.get("browser_download_url") or "",
            "digest": digest[7:] if digest.startswith("sha256:") else "",
        })
    return {"tag": body.get("tag_name") or "", "assets": assets}


def _newer(remote, local):
    return _parts(remote) > _parts(local)


def _parts(text):
    numbers = []
    for piece in str(text).lstrip("vV").split("."):
        digits = ""
        for char in piece:
            if char.isdigit():
                digits += char
            else:
                break
        numbers.append(int(digits or 0))
    return tuple(numbers)


def _quote(text):
    return "'" + text.replace("'", "'\\''") + "'"
