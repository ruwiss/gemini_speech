import array
import base64
import hashlib
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from email import message_from_bytes
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from gemini_speech.ffmpeg import require as ffmpeg_binary

ORIGIN = "https://gemini.google.com"
API_KEY = "AIzaSyD6n9asBjvx1yBHfhFhfw_kpS9Faq0BZHM"
ROTATE_URL = "https://accounts.google.com/RotateCookies"
COOKIE_PATH = os.environ.get("BROWSER_COOKIES", "")
COOKIE_LOCK = threading.Lock()
LAST_PULL = 0
HOSTS = (
    "https://speechs3proto2-pa.clients6.google.com",
    "https://speechs3proto2-pa.googleapis.com",
)
CONFIG = base64.b64decode(
    "ChViZXlvbmQtYTJhLXJlY29nbml6ZXIQAMKIjwEGEgQKAnRy4o6PAQkVAAB6RhgLIAGCx48BGBIRYmFyZC13ZWItZnJvbnRlbmRCA1dlYqLmjwFgCgRSAnRyKAHAAgGSA09iZXlvbmQtcmVjaXBlOnByb2FjdGl2ZS1vYnNlcnZlci1nZW1pbmktYXBwLXYxMC1kaXNmbHVlbmN5LXJlbW92YWwtbm8tdHJhbnNsYXRloAMB"
)
SKIP = ("beyond-a2a-recognizer", "beyond-recipe:", "bard-web-frontend")
POLL_TIMEOUT = 600


def cookie_value(header, name):
    match = re.search(r"(?:^|; )" + re.escape(name) + r"=([^;]*)", header)
    return match.group(1) if match else ""


def replace_cookie(header, name, value):
    parts = []
    found = False
    for piece in header.split(";"):
        piece = piece.strip()
        if not piece or "=" not in piece:
            continue
        key = piece.split("=", 1)[0]
        if key == name:
            parts.append(name + "=" + value)
            found = True
        else:
            parts.append(piece)
    if not found:
        parts.append(name + "=" + value)
    return "; ".join(parts)


def read_cookies():
    if not COOKIE_PATH or not os.path.exists(COOKIE_PATH):
        return ""
    header = open(COOKIE_PATH, encoding="utf-8").read().strip()
    if "SAPISID=" not in header or "__Secure-1PSID=" not in header:
        return ""
    return header


def save_cookies(header):
    if COOKIE_PATH:
        open(COOKIE_PATH, "w", encoding="utf-8").write(header)


def rotate_cookies(header):
    psid = cookie_value(header, "__Secure-1PSID")
    if not psid:
        return header
    sent = "__Secure-1PSID=" + psid
    psidts = cookie_value(header, "__Secure-1PSIDTS")
    if psidts:
        sent += "; __Secure-1PSIDTS=" + psidts
    req = urllib.request.Request(
        ROTATE_URL,
        data=b'[000,"-0000000000000000000"]',
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": sent,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            blobs = resp.headers.get_all("Set-Cookie") or []
    except Exception as exc:
        print("cookie rotate failed: %s" % exc, flush=True)
        return header
    updated = header
    for blob in blobs:
        pair = blob.split(";", 1)[0]
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        if name in ("__Secure-1PSIDTS", "__Secure-3PSIDTS", "__Secure-1PSIDRTS", "__Secure-3PSIDRTS"):
            updated = replace_cookie(updated, name, value)
    if updated != header:
        save_cookies(updated)
        print("cookie rotated", flush=True)
    return updated


def refresh_cookies(force=False):
    global LAST_PULL
    now = time.time()
    if not force and now - LAST_PULL < 600:
        header = read_cookies()
        if header:
            return header
    with COOKIE_LOCK:
        header = read_cookies()
        if header:
            header = rotate_cookies(header)
        LAST_PULL = time.time()
    return header


def cookies():
    raw = refresh_cookies()
    if "SAPISID=" not in raw:
        raise RuntimeError("browser has not sent a cookie")
    return raw


def sapisid_of(header):
    match = re.search(r"(?:^|; )SAPISID=([^;]+)", header)
    if not match:
        raise RuntimeError("SAPISID is missing")
    return match.group(1)


def auth_header(cookie):
    ts = int(time.time())
    digest = hashlib.sha1(f"{ts} {sapisid_of(cookie)} {ORIGIN}".encode()).hexdigest()
    token = f"{ts}_{digest}"
    return f"SAPISIDHASH {token} SAPISID1PHASH {token} SAPISID3PHASH {token}"


def varint(n):
    out = bytearray()
    while True:
        piece = n & 0x7F
        n >>= 7
        out.append(piece | 0x80 if n else piece)
        if not n:
            return bytes(out)


def field_bytes(number, data):
    return varint((number << 3) | 2) + varint(len(data)) + data


def field_varint(number, value):
    return varint((number << 3) | 0) + varint(value)


def webm_of(audio, name):
    ext = os.path.splitext(name or "")[1].lower() or ".wav"
    src = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        src.write(audio)
        src.close()
        proc = subprocess.run(
            [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-i", src.name,
             "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-application", "voip",
             "-b:a", "32k", "-f", "webm", "pipe:1"],
            capture_output=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    finally:
        os.unlink(src.name)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-300:] or "ffmpeg failed")
    return proc.stdout


class Channel:
    def __init__(self, host, cookie):
        self.host = host.rstrip("/")
        self.cookie = cookie
        self.url = self.host + "/s3web/prod/streaming/channel"
        self.sid = ""
        self.gsid = ""
        self.rid = 90000 + int(time.time()) % 10000
        self.chunks = []
        self.connected = threading.Event()
        self.done = threading.Event()
        self.error = ""
        self._resp = None
        self._conn = None
        self._send_lock = threading.Lock()

    def _headers(self, authed):
        headers = {
            "Origin": ORIGIN,
            "Referer": ORIGIN + "/",
            "Cookie": self.cookie,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
        }
        if authed:
            headers["Authorization"] = auth_header(self.cookie)
            headers["X-Goog-Api-Key"] = API_KEY
            headers["X-Goog-AuthUser"] = "0"
        return headers

    def open(self):
        self.rid += 1
        req = urllib.request.Request(
            self.url + "?" + urllib.parse.urlencode({
                "VER": 8, "RID": self.rid, "CVER": 22,
                "X-HTTP-Session-Id": "gsessionid", "zx": "open", "t": 1,
            }),
            data=b"count=0", method="POST",
            headers={**self._headers(True), "Content-Type": "application/x-www-form-urlencoded", "X-WebChannel-Content-Type": "application/x-protobuf"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            self.gsid = resp.headers["X-HTTP-Session-Id"]
            text = resp.read().decode()
        self.sid = re.search(r'\["c","([^"]+)"', text).group(1)
        threading.Thread(target=self._poll, daemon=True).start()
        if not self.connected.wait(8):
            raise RuntimeError("speech channel did not open")

    def _poll(self):
        url = self.url + "?" + urllib.parse.urlencode({
            "gsessionid": self.gsid, "VER": 8, "RID": "rpc", "SID": self.sid,
            "AID": 0, "CI": 0, "TYPE": "xmlhttp", "zx": "poll", "t": 1,
        })
        req = urllib.request.Request(url, headers=self._headers(True))
        try:
            # The server stays silent until the end marker arrives, so the read timeout bounds the recording length.
            with urllib.request.urlopen(req, timeout=POLL_TIMEOUT) as resp:
                self._resp = resp
                self.connected.set()
                while not self.done.is_set():
                    line = b""
                    while not line.endswith(b"\n"):
                        byte = resp.read(1)
                        if not byte:
                            return
                        line += byte
                    size = int(line.strip() or b"0")
                    body = b""
                    while len(body) < size:
                        body += resp.read(size - len(body))
                    frame = body.decode("utf-8", "replace")
                    self.chunks.append(frame)
                    if "close" in frame:
                        break
        except Exception as exc:
            if not self.done.is_set():
                self.error = str(exc)
        self._resp = None
        self.done.set()

    def close(self):
        self.done.set()
        resp = self._resp
        self._resp = None
        if resp is not None:
            # resp.close() would wait for the poll thread's blocked read; shutting the socket down wakes it.
            try:
                resp.fp.raw._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
        with self._send_lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def send(self, ofs, payload):
        self.rid += 1
        form = urllib.parse.urlencode({
            "count": "1", "ofs": str(ofs),
            "req0___data__": base64.b64encode(payload).decode(),
        })
        query = urllib.parse.urlencode({
            "VER": 8, "gsessionid": self.gsid, "SID": self.sid,
            "RID": self.rid, "AID": 0, "zx": "s" + str(ofs), "t": 1,
        })
        self._post(urllib.parse.urlsplit(self.url).path + "?" + query, form.encode())

    def _post(self, path, body):
        headers = {**self._headers(True), "Content-Type": "application/x-www-form-urlencoded"}
        with self._send_lock:
            while True:
                reused = self._conn is not None
                if not reused:
                    self._conn = http.client.HTTPSConnection(urllib.parse.urlsplit(self.url).netloc, timeout=20)
                try:
                    self._conn.request("POST", path, body, headers)
                    resp = self._conn.getresponse()
                    resp.read()
                except (http.client.HTTPException, OSError):
                    self._conn.close()
                    self._conn = None
                    # A kept-alive connection may have been dropped by the server; retry once on a fresh one.
                    if reused:
                        continue
                    raise
                if resp.status >= 400:
                    raise RuntimeError("speech channel send failed with HTTP %s" % resp.status)
                return

    def finish(self):
        self.done.wait(12)


def channel_failure(channel):
    blob = "\n".join(channel.chunks)
    if "CREDENTIALS_MISSING" in blob or ("401" in blob and "cookie" in blob):
        return "Cookie was rejected. Leave the browser open and try again."
    return channel.error or "No speech recognized"


def auth_rejected(channel):
    blob = "\n".join(channel.chunks)
    return "CREDENTIALS_MISSING" in blob or ("401" in blob and "cookie" in blob)


def good_text(text):
    text = text.strip()
    if len(text) < 2 or text in ("noop", "close") or any(skip in text for skip in SKIP):
        return False
    letters = sum(ch.isalpha() or ch.isspace() or ch in ".,!?'’-" for ch in text)
    return letters / len(text) > 0.85


def _nested_is_real(text, nested):
    plain = (text or "").strip()
    if not plain or not good_text(plain):
        return True
    return any(item and item in plain and len(plain) - len(item) <= 4 for item in nested)


def clean_transcript(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = text.replace("|", " ")
    text = re.sub(r"^[^0-9A-Za-zÇĞİÖŞÜçğıöşü]+", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def read_varint(buf, i):
    n = 0
    shift = 0
    while i < len(buf) and shift <= 28:
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7
    return None


def proto_strings(buf, depth=0):
    found = []
    i = 0
    while i < len(buf):
        parsed = read_varint(buf, i)
        if not parsed:
            break
        tag, i = parsed
        wire = tag & 7
        if wire == 0:
            parsed = read_varint(buf, i)
            if not parsed:
                break
            _, i = parsed
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        elif wire == 2:
            parsed = read_varint(buf, i)
            if not parsed:
                break
            length, i = parsed
            if length < 0 or i + length > len(buf):
                break
            chunk = buf[i:i + length]
            i += length
            nested = proto_strings(chunk, depth + 1) if depth < 4 and chunk else []
            try:
                text = chunk.decode("utf-8")
            except UnicodeDecodeError:
                text = ""
            if nested and _nested_is_real(text, nested):
                found.extend(nested)
            elif text and good_text(text):
                found.append(text)
            elif nested:
                found.extend(nested)
        else:
            break
    return found


def transcript_from(chunks):
    found = []
    for chunk in chunks:
        for blob in re.findall(r"[A-Za-z0-9+/]{16,}={0,2}", chunk):
            try:
                raw = base64.b64decode(blob + "=" * ((4 - len(blob) % 4) % 4))
            except Exception:
                continue
            for text in proto_strings(raw):
                text = clean_transcript(text)
                if text:
                    found.append(text)
    if not found:
        return ""
    best = max(found, key=len)
    for text in found:
        if text != best and text in best and len(best) - len(text) <= 4:
            best = text
    return best.strip()


def transcribe(audio, name):
    media = webm_of(audio, name)
    audio_msg = field_bytes(293101, field_bytes(1, media))
    end = field_varint(3, 1)
    cookie = cookies()
    last = None
    recognized = False
    for host in HOSTS:
        try:
            channel = Channel(host, cookie)
            channel.open()
            channel.send(0, CONFIG)
            channel.send(1, audio_msg)
            channel.send(2, end)
            channel.finish()
            text = transcript_from(channel.chunks)
            if text:
                return text
            if not auth_rejected(channel):
                recognized = True
            last = RuntimeError(channel_failure(channel))
        except Exception as exc:
            last = exc
    if recognized:
        raise RuntimeError("No speech recognized")
    raise last or RuntimeError("Speech service did not respond")


def open_channel(cookie):
    last = None
    for host in HOSTS:
        channel = None
        try:
            channel = Channel(host, cookie)
            channel.open()
            channel.send(0, CONFIG)
            return channel
        except Exception as exc:
            last = exc
            if channel is not None:
                channel.close()
    raise RuntimeError(str(last) if last else "speech channel did not open")


class Segment:
    def __init__(self, cookie, channel=None):
        self.cookie = cookie
        self.channel = channel
        self.ff = None
        self.reader = None
        self.webm = bytearray()
        self.pcm = bytearray()
        self.sent = 0
        self.ofs = 1
        self.lock = threading.Lock()
        self.ready = threading.Condition(self.lock)
        self.sender = None
        self.send_error = None
        self._draining = False
        self._released = False
        flags = {}
        if sys.platform == "win32":
            flags["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            self.ff = subprocess.Popen(
                [ffmpeg_binary(), "-hide_banner", "-loglevel", "error",
                 "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "pipe:0",
                 "-c:a", "libopus", "-application", "voip", "-b:a", "24k",
                 "-frame_duration", "20",
                 "-f", "webm", "-cluster_time_limit", "100", "-flush_packets", "1",
                 "pipe:1"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                **flags,
            )
        except Exception:
            if self.channel is not None:
                self.channel.close()
                self.channel = None
            raise
        self.reader = threading.Thread(target=self._read_webm, daemon=True)
        self.reader.start()
        self.sender = threading.Thread(target=self._stream, daemon=True)
        self.sender.start()

    def _read_webm(self):
        ff = self.ff
        if ff is None or ff.stdout is None:
            return
        while True:
            blob = ff.stdout.read1(4096)
            if not blob:
                break
            with self.lock:
                if self._released:
                    break
                self.webm.extend(blob)
                self.ready.notify()

    def _stream(self):
        if self.channel is None:
            try:
                channel = open_channel(self.cookie)
            except Exception as exc:
                self.send_error = exc
                return
            with self.lock:
                if self._released:
                    channel.close()
                    return
                self.channel = channel
        while True:
            with self.lock:
                while not self._released and not self._draining and self.sent >= len(self.webm):
                    self.ready.wait()
                if self._released:
                    return
                media = bytes(self.webm[self.sent:])
                self.sent = len(self.webm)
                if not media and self._draining:
                    return
            if not media:
                continue
            try:
                self._send_audio(media)
            except Exception as exc:
                self.send_error = exc
                return

    def _drain(self):
        with self.lock:
            self._draining = True
            self.ready.notify()
        sender = self.sender
        if sender is not None:
            sender.join(timeout=10)

    def write(self, pcm):
        if not pcm or self._released:
            return
        with self.lock:
            if self._released:
                return
            self.pcm.extend(pcm)
            ff = self.ff
        if ff is None or ff.stdin is None:
            return
        ff.stdin.write(pcm)
        ff.stdin.flush()

    def _send_audio(self, media):
        with self.lock:
            ofs = self.ofs
            self.ofs += 1
            channel = self.channel
        if channel is None or self._released:
            return
        channel.send(ofs, field_bytes(293101, field_bytes(1, media)))

    def finish(self):
        try:
            self._stop_ffmpeg(kill=False)
            self._drain()
            if self.send_error is not None:
                raise self.send_error
            with self.lock:
                streamed = len(self.webm) >= 200
                pcm = bytes(self.pcm) if not streamed and not self.sent else b""
            if pcm and self.channel is not None:
                self._send_audio(webm_of(pcm, "live.wav"))
            if self.channel is not None:
                with self.lock:
                    ofs = self.ofs
                try:
                    self.channel.send(ofs, field_varint(3, 1))
                except Exception:
                    pass
            deadline = time.time() + 8
            text = ""
            while time.time() < deadline and self.channel is not None:
                text = transcript_from(self.channel.chunks)
                if text:
                    break
                time.sleep(0.05)
            if not text:
                raise RuntimeError(channel_failure(self.channel) if self.channel else "No speech recognized")
            return text
        finally:
            self._release()

    def cancel(self):
        self._release()

    def _stop_ffmpeg(self, kill):
        ff = self.ff
        reader = self.reader
        if kill:
            self.ff = None
            self.reader = None
        if ff is None:
            if reader is not None:
                reader.join(timeout=1)
                self.reader = None
            return
        if ff.stdin is not None:
            try:
                ff.stdin.close()
            except Exception:
                pass
        if kill and ff.poll() is None:
            ff.kill()
        try:
            ff.wait(timeout=3)
        except Exception:
            try:
                ff.kill()
            except Exception:
                pass
        if reader is not None:
            reader.join(timeout=1)
        if kill or ff.poll() is not None:
            self.ff = None
            self.reader = None

    def _release(self):
        with self.lock:
            if self._released:
                return
            self._released = True
            self.webm = bytearray()
            self.pcm = bytearray()
            self.ready.notify_all()
        self._stop_ffmpeg(kill=True)
        channel = self.channel
        self.channel = None
        if channel is not None:
            channel.chunks.clear()
            channel.close()


def pcm_level(pcm):
    samples = array.array("h", pcm[:len(pcm) // 2 * 2])
    if not samples:
        return 0.0
    return sum(abs(sample) for sample in samples) / len(samples)


def _word_key(word):
    return re.sub(r"\W+", "", word.casefold())


def merge_overlap(left, right):
    # The recognizer drops an unfinished trailing phrase, so the left side may end well before the cut.
    # Find where the left side's last words reappear inside the overlapped start of the right side.
    a, b = left.split(), right.split()
    ka, kb = [_word_key(w) for w in a], [_word_key(w) for w in b]
    best = (0, 0, 0)
    for a_end in range(len(ka), max(len(ka) - 3, 0), -1):
        for b_end in range(1, min(len(kb), 80) + 1):
            k = 0
            while k < a_end and k < b_end and ka[a_end - 1 - k] and ka[a_end - 1 - k] == kb[b_end - 1 - k]:
                k += 1
            if k > best[0]:
                best = (k, a_end, b_end)
    k, a_end, b_end = best
    if k >= 2 or (k == 1 and b_end <= 2):
        return " ".join(a[:a_end - 1] + b[b_end - 1:])
    return left + " " + right


class Live:
    # The recognizer returns nothing for a single stream longer than roughly 40-45 seconds.
    # The next segment starts listening at NEXT_SECONDS so it already holds the overlap in real time
    # when the current one is cut; sending the overlap in one burst would delay its result by seconds.
    NEXT_SECONDS = 20
    SEGMENT_SECONDS = 25
    RELAXED_SECONDS = 30
    SEGMENT_LIMIT = 35
    BYTES_PER_SECOND = 32000
    WINDOW = 640
    PAUSE = 8000
    SHORT_PAUSE = 3840

    def __init__(self):
        self.cookie = cookies()
        self.current = Segment(self.cookie, open_channel(self.cookie))
        self.current_overlap = False
        self.next = None
        self.next_length = 0
        self.done = []
        self.length = 0
        self.quiet = 0
        self.level = 0.0
        self.lock = threading.Lock()
        self._released = False

    def write(self, pcm):
        if not pcm:
            return
        with self.lock:
            while pcm and not self._released:
                cut = self._find_cut(pcm)
                head, pcm = (pcm, b"") if cut < 0 else (pcm[:cut], pcm[cut:])
                self.current.write(head)
                if self.next is not None:
                    self.next.write(head)
                    self.next_length += len(head)
                elif self.length >= self.NEXT_SECONDS * self.BYTES_PER_SECOND:
                    self.next = Segment(self.cookie)
                    self.next_length = 0
                if cut >= 0:
                    self._cut()

    def _find_cut(self, pcm):
        for offset in range(0, len(pcm), self.WINDOW):
            window = pcm[offset:offset + self.WINDOW]
            level = pcm_level(window)
            quiet = self.level > 0 and level < self.level * 0.3
            self.level = level if not self.level else self.level * 0.98 + level * 0.02
            self.quiet = self.quiet + len(window) if quiet else 0
            self.length += len(window)
            seconds = self.length / self.BYTES_PER_SECOND
            pause = self.PAUSE if seconds < self.RELAXED_SECONDS else self.SHORT_PAUSE
            if seconds >= self.SEGMENT_SECONDS and self.quiet >= pause or seconds >= self.SEGMENT_LIMIT:
                return offset + len(window)
        return -1

    def _cut(self):
        # Segments overlap because the recognizer drops unfinished phrases and punctuates each stream
        # as a finished utterance; merge_overlap repairs both at the seam.
        box = {"segment": self.current, "overlap": self.current_overlap}
        box["thread"] = threading.Thread(target=self._finish_segment, args=(box,), daemon=True)
        self.done.append(box)
        box["thread"].start()
        self.current_overlap = self.next is not None
        self.current = self.next or Segment(self.cookie)
        self.length = self.next_length if self.next is not None else 0
        self.next = None
        self.quiet = 0

    @staticmethod
    def _finish_segment(box):
        try:
            box["text"] = box["segment"].finish()
        except Exception as exc:
            box["error"] = exc

    def _drop_next(self):
        if self.next is not None:
            self.next.cancel()
            self.next = None

    def finish(self):
        with self.lock:
            self._released = True
            self._drop_next()
            boxes = self.done + [{"segment": self.current, "overlap": self.current_overlap}]
        self._finish_segment(boxes[-1])
        for box in boxes[:-1]:
            box["thread"].join(timeout=15)
        text = ""
        for box in boxes:
            part = box.get("text")
            if not part:
                continue
            text = merge_overlap(text, part) if text and box["overlap"] else (text + " " + part).strip()
        if text:
            return text
        errors = [box["error"] for box in boxes if box.get("error")]
        raise errors[-1] if errors else RuntimeError("No speech recognized")

    def cancel(self):
        with self.lock:
            self._released = True
            self._drop_next()
            segments = [box["segment"] for box in self.done] + [self.current]
        for segment in segments:
            segment.cancel()


LIVES = {}
LIVES_LOCK = threading.Lock()


def parse_form(content_type, body):
    raw = b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    msg = message_from_bytes(raw, policy=default)
    fields, name, data = {}, "audio.wav", b""
    if not msg.is_multipart():
        return fields, name, data
    for part in msg.iter_parts():
        if "form-data" not in (part.get("Content-Disposition") or ""):
            continue
        filename = part.get_param("filename", header="Content-Disposition")
        payload = part.get_payload(decode=True) or b""
        if filename:
            name, data = filename, payload
        else:
            key = part.get_param("name", header="Content-Disposition")
            if key:
                fields[key] = payload.decode("utf-8", "replace")
    return fields, name, data


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] in ("/health", "/v1/health"):
            self._json(200, {"status": "ok"})
            return
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/v1/live":
            try:
                live = Live()
            except Exception as exc:
                self._json(502, {"error": {"message": str(exc)[:500]}})
                return
            sid = uuid.uuid4().hex
            with LIVES_LOCK:
                LIVES[sid] = live
            self._json(200, {"id": sid})
            return
        if path.startswith("/v1/live/") and (path.endswith("/finish") or path.endswith("/cancel")):
            ending = "/finish" if path.endswith("/finish") else "/cancel"
            sid = path[len("/v1/live/"):-len(ending)]
            with LIVES_LOCK:
                live = LIVES.pop(sid, None)
            if live is None:
                self._json(404, {"error": {"message": "session is gone"}})
                return
            if ending == "/cancel":
                live.cancel()
                self._json(200, {"ok": True})
                return
            try:
                text = live.finish()
            except Exception as exc:
                self._json(502, {"error": {"message": str(exc)[:500]}})
                return
            self._json(200, {"text": text})
            return
        if path.startswith("/v1/live/"):
            sid = path[len("/v1/live/"):]
            with LIVES_LOCK:
                live = LIVES.get(sid)
            if live is None:
                self._json(404, {"error": {"message": "session is gone"}})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                live.write(self.rfile.read(length))
            except Exception as exc:
                self._json(502, {"error": {"message": str(exc)[:500]}})
                return
            self._json(200, {"ok": True})
            return
        if path not in ("/v1/audio/transcriptions", "/audio/transcriptions"):
            self._json(404, {"error": {"message": "not found"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        try:
            _fields, name, audio = parse_form(self.headers.get("Content-Type") or "", body)
            if not audio:
                raise RuntimeError("audio file is empty")
            text = transcribe(audio, name)
        except Exception as exc:
            self._json(502, {"error": {"message": str(exc)[:500]}})
            return
        self._json(200, {"text": text})

    def _json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


def keeper():
    while True:
        try:
            refresh_cookies(True)
        except Exception as exc:
            print("cookie keeper: %s" % exc, flush=True)
        time.sleep(600)


def parent_alive(pid):
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def watch_parent():
    raw = os.environ.get("GEMINI_SPEECH_PARENT") or ""
    if not raw.isdigit():
        return
    parent = int(raw)
    while True:
        time.sleep(1)
        if not parent_alive(parent):
            os._exit(0)


def serve():
    threading.Thread(target=watch_parent, daemon=True).start()
    threading.Thread(target=keeper, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "4982"))), Handler).serve_forever()


if __name__ == "__main__":
    serve()
