import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")


def png_to_ico(png_path, ico_path):
    data = open(png_path, "rb").read()
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(data), 22)
    open(ico_path, "wb").write(header + entry + data)


def run(cmd):
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)


def pyinstaller(spec, dist_name):
    target = os.path.join(DIST, dist_name)
    if os.path.isdir(target):
        shutil.rmtree(target)
    flat = os.path.join(DIST, dist_name + (".exe" if sys.platform == "win32" else ""))
    if os.path.isfile(flat):
        os.remove(flat)
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", DIST,
        "--workpath", os.path.join(WORK, dist_name),
        spec,
    ])


def _iscc():
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return found
    for path in (
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    ):
        if os.path.isfile(path):
            return path
    return ""


def package_windows():
    iscc = _iscc()
    if not iscc:
        raise SystemExit("Inno Setup 6 was not found")
    run([iscc, os.path.join(ROOT, "packaging", "windows", "setup.iss")])
    print(os.path.join(DIST, "GeminiSpeechAPI-Setup.exe"))


def package_mac():
    app_path = os.path.join(DIST, "GeminiSpeechAPI.app")
    if not os.path.isdir(app_path):
        raise SystemExit("macOS app was not built")
    staging = os.path.join(DIST, "dmg-stage")
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)
    shutil.copytree(app_path, os.path.join(staging, "GeminiSpeechAPI.app"), symlinks=True)
    dmg = os.path.join(DIST, "GeminiSpeechAPI-macos.dmg")
    if os.path.exists(dmg):
        os.remove(dmg)
    subprocess.check_call([
        "hdiutil", "create", "-volname", "GeminiSpeechAPI",
        "-srcfolder", staging, "-ov", "-format", "UDZO", dmg,
    ])
    shutil.rmtree(staging)
    print(dmg)


def package_linux():
    folder = os.path.join(DIST, "GeminiSpeechAPI")
    if not os.path.isdir(folder):
        raise SystemExit("Linux app was not built")
    archive = os.path.join(DIST, "GeminiSpeechAPI-linux.tar.gz")
    if os.path.exists(archive):
        os.remove(archive)
    shutil.make_archive(
        os.path.join(DIST, "GeminiSpeechAPI-linux"),
        "gztar",
        DIST,
        "GeminiSpeechAPI",
    )
    print(archive)


def main():
    os.chdir(ROOT)
    png_to_ico(
        os.path.join(ROOT, "assets", "icon.png"),
        os.path.join(ROOT, "assets", "icon.ico"),
    )
    pyinstaller(os.path.join(ROOT, "packaging", "app.spec"), "GeminiSpeechAPI")
    if sys.platform == "win32":
        package_windows()
    elif sys.platform == "darwin":
        package_mac()
    else:
        package_linux()


if __name__ == "__main__":
    main()
