import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gemini_speech.paths import cookies_path


def read_msg():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    size = struct.unpack("<I", raw)[0]
    return json.loads(sys.stdin.buffer.read(size).decode("utf-8"))


def write_msg(payload):
    body = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(body)))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def run():
    msg = read_msg()
    header = (msg or {}).get("cookie") or ""
    if "SAPISID=" not in header or "__Secure-1PSID=" not in header:
        write_msg({"ok": False})
        return
    path = os.environ.get("GEMINI_SPEECH_COOKIES") or cookies_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(header)
    write_msg({"ok": True})


if __name__ == "__main__":
    run()
