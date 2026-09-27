import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")
APP = os.path.join(DIST, "GeminiSpeech")


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


def host_binary():
    name = "cookie_host.exe" if sys.platform == "win32" else "cookie_host"
    candidates = [
        os.path.join(DIST, name),
        os.path.join(DIST, "cookie_host", name),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise SystemExit("cookie host binary was not built")


def assemble():
    os.makedirs(APP, exist_ok=True)
    host = host_binary()
    shutil.copy2(host, os.path.join(APP, os.path.basename(host)))
    ext = os.path.join(APP, "extension")
    if os.path.isdir(ext):
        shutil.rmtree(ext)
    shutil.copytree(os.path.join(ROOT, "extension"), ext)
    assets = os.path.join(APP, "assets")
    os.makedirs(assets, exist_ok=True)
    shutil.copy2(os.path.join(ROOT, "assets", "icon.png"), os.path.join(assets, "icon.png"))
    for name in ("cookie_host.cmd", "cookie_host.sh", "cookie_host.py"):
        shutil.copy2(os.path.join(ROOT, name), os.path.join(APP, name))
    if sys.platform != "win32":
        os.chmod(os.path.join(APP, "cookie_host.sh"), 0o755)


def package_windows():
    iscc = _iscc()
    if not iscc:
        print("Inno Setup not found. Folder is ready at dist\\GeminiSpeech")
        print("Install Inno Setup 6, then run packaging\\build.py again for GeminiSpeech-Setup.exe")
        return
    run([iscc, os.path.join(ROOT, "packaging", "windows", "setup.iss")])
    print(os.path.join(DIST, "GeminiSpeech-Setup.exe"))


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


def package_mac(app_path):
    host = host_binary()
    macos = os.path.join(app_path, "Contents", "MacOS")
    os.makedirs(macos, exist_ok=True)
    shutil.copy2(host, os.path.join(macos, "cookie_host"))
    os.chmod(os.path.join(macos, "cookie_host"), 0o755)
    ext = os.path.join(macos, "extension")
    if os.path.isdir(ext):
        shutil.rmtree(ext)
    shutil.copytree(os.path.join(ROOT, "extension"), ext)
    shutil.copy2(os.path.join(ROOT, "cookie_host.sh"), os.path.join(macos, "cookie_host.sh"))
    os.chmod(os.path.join(macos, "cookie_host.sh"), 0o755)
    dmg = os.path.join(DIST, "GeminiSpeech.dmg")
    if os.path.exists(dmg):
        os.remove(dmg)
    staging = os.path.join(DIST, "dmg")
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)
    shutil.copytree(app_path, os.path.join(staging, "Gemini Speech.app"))
    subprocess.check_call([
        "hdiutil", "create", "-volname", "Gemini Speech",
        "-srcfolder", staging, "-ov", "-format", "UDZO", dmg,
    ])
    print(dmg)


def package_linux():
    shutil.copy2(
        os.path.join(ROOT, "packaging", "linux", "install.sh"),
        os.path.join(APP, "install.sh"),
    )
    os.chmod(os.path.join(APP, "install.sh"), 0o755)
    archive = os.path.join(DIST, "GeminiSpeech-linux.tar.gz")
    if os.path.exists(archive):
        os.remove(archive)
    shutil.make_archive(archive[:-7], "gztar", DIST, "GeminiSpeech")
    print(archive)
    print("On the target machine: tar -xzf GeminiSpeech-linux.tar.gz && ./GeminiSpeech/install.sh")


def main():
    os.chdir(ROOT)
    png_to_ico(
        os.path.join(ROOT, "assets", "icon.png"),
        os.path.join(ROOT, "assets", "icon.ico"),
    )
    pyinstaller(os.path.join(ROOT, "packaging", "host.spec"), "cookie_host")
    pyinstaller(os.path.join(ROOT, "packaging", "app.spec"), "GeminiSpeech")
    if sys.platform == "darwin":
        app_path = os.path.join(DIST, "Gemini Speech.app")
        if not os.path.isdir(app_path):
            app_path = os.path.join(DIST, "GeminiSpeech.app")
        package_mac(app_path)
        return
    assemble()
    if sys.platform == "win32":
        package_windows()
        return
    package_linux()


if __name__ == "__main__":
    main()
