import base64
import json
import os
import queue
import select
import socket
import ssl
import threading
import urllib.parse

from . import messages

HOST = "generativelanguage.googleapis.com"
PATH = (
    "/ws/google.ai.generativelanguage.v1beta.GenerativeService."
    "BidiGenerateContent"
)
RATE = 16000
WIDTH = 2
CHUNK = 3200  # 100 ms, 1600 frames
MAX_PCM = 10 * 60 * RATE * WIDTH
MIN_PCM = RATE * WIDTH // 5
MIME = "audio/pcm;rate=16000"


class LiveSession:
    def __init__(self, api_key, language=""):
        self._key = (api_key or "").strip()
        self._language = (language or "").strip()
        self._queue = queue.Queue()
        self._thread = None
        self._sock = None
        self._buf = bytearray()
        self._finals = []
        self._interim = ""
        self._sent = 0
        self._closing = False
        self.text = ""
        self.error = ""
        self._opened = 0.0
        self._end_seen = False
        self.limit_hit = threading.Event()
        self.done = threading.Event()

    def fresh(self):
        if self.done.is_set() or self.error:
            return False
        if self._opened and _now() - self._opened > 8 * 60:
            return False
        return True

    def open(self):
        if not self._key:
            raise RuntimeError(messages.API_KEY_MISSING)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def push(self, pcm):
        if pcm and not self.done.is_set():
            self._queue.put(pcm)

    def finish(self):
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=25)
        if self.text.strip():
            return self.text.strip()
        if self.error:
            raise RuntimeError(self.error)
        raise RuntimeError(messages.NO_SPEECH)

    def cancel(self):
        self._closing = True
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self):
        try:
            self._sock = _connect(self._key)
            self._send(self._setup_message())
            setup = self._next_message(15)
            if setup is None or "setupComplete" not in setup:
                raise RuntimeError(_failure(setup, self._key))
            self._opened = _now()
            pending = bytearray()
            ending = False
            while not self._closing:
                self._drain(0)
                if self.error:
                    break
                item = self._take(0 if pending else 0.02)
                if item:
                    pending.extend(item)
                if item is None or self._end_seen:
                    ending = True
                while pending and (ending or len(pending) >= CHUNK):
                    if self._sent >= MAX_PCM:
                        self.limit_hit.set()
                        pending.clear()
                        ending = True
                        break
                    size = len(pending) if ending else CHUNK
                    if self._sent + size > MAX_PCM:
                        size = MAX_PCM - self._sent
                    self._send_audio(bytes(pending[:size]))
                    del pending[:size]
                if not ending:
                    continue
                if self._sent < MIN_PCM:
                    raise RuntimeError(messages.RECORDING_TOO_SHORT)
                self._send_audio(b"\x00" * (RATE * WIDTH * 3 // 10))
                self._send({"realtimeInput": {"audioStreamEnd": True}})
                self._collect_final()
                break
            self.text = self._text()
            if not self.text and not self.error and not self._closing:
                if self.limit_hit.is_set():
                    self.error = messages.RECORDING_TOO_LONG
                else:
                    self.error = messages.NO_SPEECH
        except Exception as exc:
            if not self._closing:
                self.error = _redact(str(exc), self._key)[:80] or messages.REQUEST_FAILED
        finally:
            self._close()
            self.done.set()

    def _send_audio(self, pcm):
        self._sent += len(pcm)
        self._send({
            "realtimeInput": {
                "audio": {
                    "data": base64.b64encode(pcm).decode("ascii"),
                    "mimeType": MIME,
                },
            },
        })

    def _take(self, timeout):
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return False
        if item is None:
            self._end_seen = True
            return None
        blob = bytearray(item)
        while True:
            try:
                extra = self._queue.get_nowait()
            except queue.Empty:
                break
            if extra is None:
                self._end_seen = True
                break
            blob.extend(extra)
        return bytes(blob)

    def _text(self):
        parts = [piece.strip() for piece in self._finals if piece and piece.strip()]
        interim = self._interim.strip()
        if interim:
            parts.append(interim)
        return " ".join(parts)

    def _collect_final(self):
        # The interim already on screen was produced before the tail audio
        # arrived. Returning it drops the last words.
        baseline = self._interim
        base_count = len(self._finals)
        deadline = _now() + 1.0
        current = baseline
        changed_at = None
        while _now() < deadline and not self._closing:
            self._drain(0.05)
            if len(self._finals) > base_count:
                self._drain(0.1)
                return
            if self._interim and self._interim != baseline:
                if self._interim != current:
                    current = self._interim
                    changed_at = _now()
                elif changed_at and _now() - changed_at >= 0.25:
                    return

    def _drain(self, timeout):
        got = False
        while True:
            message = self._next_message(0 if got else timeout)
            if message is None:
                return got
            got = True
            self._apply(message)

    def _apply(self, message):
        if "error" in message:
            self.error = _failure(message, self._key)
            return
        content = message.get("serverContent") or {}
        if self._language:
            interim = content.get("interimOutputTranscription") or {}
            final = content.get("outputTranscription") or {}
        else:
            interim = content.get("interimInputTranscription") or {}
            final = content.get("inputTranscription") or {}
        if interim.get("text"):
            self._interim = interim["text"]
        if final.get("text"):
            self._finals.append(final["text"])
            self._interim = ""

    def _setup_message(self):
        if self._language:
            return {
                "setup": {
                    "model": "models/gemini-3.5-live-translate-preview",
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "translationConfig": {
                            "targetLanguageCode": self._language,
                            "echoTargetLanguage": True,
                        },
                    },
                    "inputAudioTranscription": {},
                    "outputAudioTranscription": {},
                },
            }
        return {
            "setup": {
                "model": "models/gemini-3.5-transcribe-live",
                "generationConfig": {"responseModalities": ["TEXT"]},
                "inputAudioTranscription": {"mode": "SMART"},
            },
        }

    def _send(self, payload):
        _send_frame(self._sock, 1, json.dumps(payload).encode("utf-8"))

    def _next_message(self, timeout):
        payload = _read_message(self._sock, self._buf, timeout)
        if payload is None:
            return None
        if not payload:
            return {}
        return json.loads(payload.decode("utf-8"))

    def _close(self):
        sock = self._sock
        self._sock = None
        if sock is None:
            return
        try:
            _send_frame(sock, 8, b"")
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass


def _connect(key):
    raw = socket.create_connection((HOST, 443), timeout=20)
    sock = ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
    nonce = base64.b64encode(os.urandom(16)).decode("ascii")
    query = urllib.parse.urlencode({"key": key})
    request = (
        "GET %s?%s HTTP/1.1\r\n"
        "Host: %s\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: %s\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    ) % (PATH, query, HOST, nonce)
    sock.sendall(request.encode("ascii"))
    status, leftover = _read_headers(sock)
    if b" 101 " not in status:
        detail = status.decode("utf-8", errors="replace").split("\r\n", 1)[0]
        raise RuntimeError(_redact(detail, key) or messages.REQUEST_FAILED)
    sock.settimeout(None)
    holder = _Socket(sock, leftover)
    return holder


class _Socket:
    def __init__(self, sock, leftover):
        self.sock = sock
        self.pending_bytes = bytearray(leftover)

    def close(self):
        self.sock.close()


def _read_headers(sock):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > 65536:
            break
    head, _, rest = bytes(data).partition(b"\r\n\r\n")
    return head, rest


def _send_frame(holder, opcode, payload):
    mask = os.urandom(4)
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(length.to_bytes(2, "big"))
    else:
        header.append(0x80 | 127)
        header.extend(length.to_bytes(8, "big"))
    header.extend(mask)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    holder.sock.sendall(header + masked)


def _read_message(holder, carry, timeout):
    pieces = []
    opcode = None
    while True:
        frame = _read_frame(holder, carry, timeout if not pieces else 5)
        if frame is None:
            return None
        fin, kind, payload = frame
        if kind == 9:
            _send_frame(holder, 10, payload)
            continue
        if kind == 8:
            reason = payload[2:].decode("utf-8", errors="replace") if len(payload) > 2 else ""
            raise RuntimeError(reason or messages.REQUEST_FAILED)
        if kind in (1, 2):
            opcode = kind
            pieces.append(payload)
        elif kind == 0 and pieces:
            pieces.append(payload)
        if fin and pieces:
            return b"".join(pieces)
        if opcode is None and fin:
            return b""


def _read_frame(holder, carry, timeout):
    if not _wait(holder, carry, timeout):
        return None
    head = _exact(holder, carry, 2)
    first, second = head[0], head[1]
    length = second & 0x7F
    if length == 126:
        length = int.from_bytes(_exact(holder, carry, 2), "big")
    elif length == 127:
        length = int.from_bytes(_exact(holder, carry, 8), "big")
    mask = _exact(holder, carry, 4) if second & 0x80 else b""
    payload = _exact(holder, carry, length)
    if mask:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return bool(first & 0x80), first & 0x0F, payload


def _wait(holder, carry, timeout):
    if len(carry) or holder.pending_bytes or holder.sock.pending():
        return True
    readable, _, _ = select.select([holder.sock], [], [], timeout)
    return bool(readable)


def _exact(holder, carry, size):
    while len(carry) < size:
        if holder.pending_bytes:
            carry.extend(holder.pending_bytes)
            holder.pending_bytes.clear()
            continue
        chunk = holder.sock.recv(max(4096, size - len(carry)))
        if not chunk:
            raise RuntimeError(messages.REQUEST_FAILED)
        carry.extend(chunk)
    out = bytes(carry[:size])
    del carry[:size]
    return out


def _failure(message, key):
    if not message:
        return messages.REQUEST_FAILED
    error = message.get("error") or {}
    text = error.get("message") or error.get("status") or messages.REQUEST_FAILED
    return _redact(str(text), key)[:80]


def _redact(text, key):
    if key:
        text = text.replace(key, "")
    return " ".join(text.split())


def _now():
    return __import__("time").monotonic()
