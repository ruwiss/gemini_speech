import json
import os
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


def download():
    if not getattr(sys, "frozen", False):
        return ""
    name = ASSETS.get(sys.platform)
    if not name:
        return ""
    remote = _latest()
    if not remote or not _newer(remote["tag"], __version__):
        return ""
    asset = next((item for item in remote["assets"] if item.get("name") == name), None)
    if not asset:
        return ""
    target = os.path.join(tempfile.gettempdir(), name)
    request = urllib.request.Request(
        asset["url"],
        headers={"User-Agent": "GeminiSpeechAPI", "Accept": "application/octet-stream"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    open(target, "wb").write(data)
    return target


def launch(path):
    if sys.platform == "win32":
        subprocess.Popen(
            [path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            close_fds=True,
        )
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", path], close_fds=True)
        return
    folder = os.path.dirname(sys.executable)
    script = os.path.join(tempfile.gettempdir(), "geminispeech-update.sh")
    open(script, "w", encoding="utf-8").write(
        "#!/bin/sh\n"
        "while kill -0 %s 2>/dev/null; do sleep 0.2; done\n"
        "tar -xzf %s -C %s\n"
        "exec %s\n" % (os.getpid(), _quote(path), _quote(os.path.dirname(folder)), _quote(sys.executable))
    )
    os.chmod(script, 0o755)
    subprocess.Popen(["/bin/sh", script], start_new_session=True)
    os._exit(0)


def _latest():
    request = urllib.request.Request(API, headers={"User-Agent": "GeminiSpeechAPI"})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))
    assets = []
    for item in body.get("assets") or []:
        assets.append({
            "name": item.get("name") or "",
            "url": item.get("url") or "",
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
