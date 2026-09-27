import json
import os
import stat
import sys

from . import paths

HOST = "com.gemini.speech"
ORIGIN = "chrome-extension://ikbedfcebmnjlmkkeakknmapgghipnea/"

_WIN = (
    r"Software\Google\Chrome\NativeMessagingHosts\%s" % HOST,
    r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\%s" % HOST,
    r"Software\Microsoft\Edge\NativeMessagingHosts\%s" % HOST,
    r"Software\Chromium\NativeMessagingHosts\%s" % HOST,
)
_MAC = (
    "Google/Chrome",
    "BraveSoftware/Brave-Browser",
    "Microsoft Edge",
    "Chromium",
)
_LINUX = (
    "google-chrome",
    "chromium",
    "BraveSoftware/Brave-Browser",
    "microsoft-edge",
)
_FLATPAK = (
    ("com.google.Chrome", "google-chrome"),
    ("com.brave.Browser", "BraveSoftware/Brave-Browser"),
    ("org.chromium.Chromium", "chromium"),
    ("com.microsoft.Edge", "microsoft-edge"),
)


def launcher():
    if sys.platform == "win32":
        exe = os.path.join(paths.ROOT, "cookie_host.exe")
        if os.path.isfile(exe):
            return exe
        return os.path.join(paths.ROOT, "cookie_host.cmd")
    binary = os.path.join(paths.ROOT, "cookie_host")
    if os.path.isfile(binary):
        _mark_exec(binary)
        return binary
    path = os.path.join(paths.ROOT, "cookie_host.sh")
    if os.path.isfile(path):
        _mark_exec(path)
    return path


def install():
    payload = {
        "name": HOST,
        "description": "Gemini Speech cookie host",
        "path": launcher(),
        "type": "stdio",
        "allowed_origins": [ORIGIN],
    }
    manifest = paths.host_manifest()
    open(manifest, "w", encoding="utf-8").write(json.dumps(payload))
    if sys.platform == "win32":
        _windows(manifest)
    elif sys.platform == "darwin":
        _dirs(os.path.expanduser("~/Library/Application Support"), _MAC, manifest)
    else:
        _dirs(os.path.expanduser("~/.config"), _LINUX, manifest)
        _flatpak(manifest)


def _mark_exec(path):
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _windows(manifest):
    import winreg
    for target in _WIN:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, target)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, manifest)
        winreg.CloseKey(key)


def _dirs(base, names, manifest):
    text = open(manifest, encoding="utf-8").read()
    for name in names:
        dest = os.path.join(base, name, "NativeMessagingHosts")
        os.makedirs(dest, exist_ok=True)
        open(os.path.join(dest, HOST + ".json"), "w", encoding="utf-8").write(text)


def _flatpak(manifest):
    text = open(manifest, encoding="utf-8").read()
    home = os.path.expanduser("~/.var/app")
    for app_id, config_name in _FLATPAK:
        root = os.path.join(home, app_id)
        if not os.path.isdir(root):
            continue
        dest = os.path.join(root, "config", config_name, "NativeMessagingHosts")
        os.makedirs(dest, exist_ok=True)
        open(os.path.join(dest, HOST + ".json"), "w", encoding="utf-8").write(text)
