# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "assets", "icon.ico")

# pynput imports an X display at import time. Headless CI needs xvfb-run, and
# Linux backends are listed explicitly so the freeze still picks them up.
hiddenimports = ["PyQt6.QtMultimedia", "certifi"]
if sys.platform.startswith("linux"):
    hiddenimports += [
        "pynput",
        "pynput.keyboard",
        "pynput.keyboard._base",
        "pynput.keyboard._xorg",
        "pynput.mouse",
        "pynput.mouse._base",
        "pynput.mouse._xorg",
        "pynput._util",
        "pynput._util.xorg",
        "Xlib",
        "Xlib.display",
        "Xlib.X",
        "Xlib.XK",
        "Xlib.ext",
        "Xlib.ext.xtest",
        "Xlib.ext.record",
        "Xlib.protocol",
        "Xlib.protocol.event",
        "Xlib.protocol.request",
        "Xlib.protocol.rq",
        "Xlib.support",
        "Xlib.support.connect",
        "Xlib.support.lock",
        "Xlib.support.unix_connect",
        "Xlib.threaded",
        "Xlib.keysymdef",
        "Xlib.keysymdef.miscellany",
        "Xlib.keysymdef.latin1",
        "Xlib.keysymdef.xkb",
        "evdev",
        "evdev.ecodes",
        "six",
    ]
elif sys.platform == "darwin":
    hiddenimports += [
        "pynput",
        "pynput.keyboard",
        "pynput.keyboard._base",
        "pynput.keyboard._darwin",
        "pynput.mouse",
        "pynput.mouse._base",
        "pynput.mouse._darwin",
        "pynput._util",
        "pynput._util.darwin",
    ]

datas = [(os.path.join(ROOT, "assets"), "assets")]
datas += collect_data_files("certifi")

a = Analysis(
    [os.path.join(ROOT, "launch.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GeminiSpeechAPI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON if os.path.isfile(ICON) else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GeminiSpeechAPI",
)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="GeminiSpeechAPI.app",
        bundle_identifier="com.geminispeech.api",
    )
