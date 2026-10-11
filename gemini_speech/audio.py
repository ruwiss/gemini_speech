import sys
import threading
import time

from PyQt6.QtCore import QMetaObject, QObject, QThread, QTimer, Qt, Q_ARG, pyqtSlot
from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSource, QMediaDevices

from . import messages

RATE = 16000
WIDTH = 2
# Deep enough that a late read still returns the samples instead of a hole.
BUFFER = RATE * WIDTH // 2


class _Engine(QObject):
    """Microphone owner. It lives on its own thread so the overlay cannot stall it."""

    def __init__(self):
        super().__init__()
        self.on_chunk = None
        self._source = None
        self._io = None
        self._pump = None
        self._chunks = []
        self._mark = 0
        self._lock = threading.Lock()
        self._running = False
        self._error = ""
        self._reading = False
        self._heard_at = 0.0
        self._com = False
        self.ready = None

    @property
    def running(self):
        with self._lock:
            return self._running

    @pyqtSlot()
    def mark_ready(self):
        if self.ready is not None:
            self.ready()

    @pyqtSlot(str)
    def start_capture(self, device_id):
        self._error = ""
        self.stop_capture()
        try:
            self._open(device_id)
        except Exception as exc:
            self._fail(str(exc)[:80] or messages.MICROPHONE_NOT_OPEN)

    @pyqtSlot()
    def stop_capture(self):
        pump = self._pump
        source = self._source
        io = self._io
        self._pump = None
        self._source = None
        self._io = None
        if pump is not None:
            pump.stop()
            pump.deleteLater()
        if io is not None:
            try:
                io.readyRead.disconnect(self._read)
            except Exception:
                pass
        if source is not None:
            source.stop()
        if io is not None:
            data = bytes(io.readAll())
            if data:
                self._keep(data, gap=False)
        with self._lock:
            self._running = False
            self._chunks = []
            self._mark = 0
        self._heard_at = 0.0

    def mark(self):
        with self._lock:
            self._mark = sum(len(chunk) for chunk in self._chunks)

    def since_mark(self):
        with self._lock:
            data = b"".join(self._chunks)
            mark = self._mark
        if mark >= len(data):
            return b""
        return data[mark:]

    def _open(self, device_id):
        self._join_com()
        fmt = QAudioFormat()
        fmt.setSampleRate(RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        device = input_device(device_id)
        if device.isNull():
            raise RuntimeError(messages.NO_MICROPHONE)
        source = QAudioSource(device, fmt)
        source.setBufferSize(BUFFER)
        io = source.start()
        if io is None:
            source.stop()
            raise RuntimeError(messages.MICROPHONE_NOT_OPEN)
        # Underrun is reported later, when the buffer was not read in time.
        if source.error() not in (QAudio.Error.NoError, QAudio.Error.UnderrunError):
            detail = source.error()
            source.stop()
            raise RuntimeError("%s (%s)" % (messages.MICROPHONE_NOT_OPEN, detail))
        self._source = source
        self._io = io
        self._heard_at = 0.0
        with self._lock:
            self._chunks = []
            self._mark = 0
            self._running = True
        io.readyRead.connect(self._read)
        pump = QTimer(self)
        pump.setInterval(15)
        pump.timeout.connect(self._read)
        pump.start()
        self._pump = pump
        self._read()

    def _join_com(self):
        if self._com or sys.platform != "win32":
            return
        import ctypes
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)
        self._com = True

    def _fail(self, text):
        self.stop_capture()
        self._error = text

    def _read(self):
        io = self._io
        if io is None or self._reading:
            return
        self._reading = True
        try:
            data = bytes(io.readAll())
        finally:
            self._reading = False
        if data:
            self._keep(data, gap=True)

    def _keep(self, data, gap):
        # A late driver hands back less audio than the time that passed.
        # Silence keeps the clock, so the lost stretch is not spliced together.
        if gap and self._heard_at:
            late = time.monotonic() - self._heard_at - (len(data) / float(RATE * WIDTH))
            if late > 0.06:
                samples = int(min(late, 0.4) * RATE)
                if samples > 0:
                    self._emit(b"\x00" * (samples * WIDTH))
        self._heard_at = time.monotonic()
        self._emit(data)

    def _emit(self, data):
        if not data:
            return
        with self._lock:
            self._chunks.append(data)
        callback = self.on_chunk
        if callback is not None:
            callback(data)


class Recorder:
    def __init__(self):
        self.on_chunk = None
        self._ready = threading.Event()
        self._thread = QThread()
        self._thread.setObjectName("microphone")
        self._engine = _Engine()
        self._engine.ready = self._ready.set
        self._engine.moveToThread(self._thread)
        # Queued, so this runs only after the thread is inside its event loop.
        self._thread.started.connect(self._engine.mark_ready, Qt.ConnectionType.QueuedConnection)
        self._thread.start(QThread.Priority.HighPriority)

    def start(self, device_id=""):
        self._wait_ready()
        self._engine.on_chunk = self.on_chunk
        QMetaObject.invokeMethod(
            self._engine,
            "start_capture",
            Qt.ConnectionType.BlockingQueuedConnection,
            Q_ARG(str, device_id or ""),
        )
        if self._engine._error or not self._engine.running:
            raise RuntimeError(self._engine._error or messages.MICROPHONE_NOT_OPEN)

    def stop(self):
        if not self._ready.is_set():
            return b""
        self._engine.on_chunk = self.on_chunk
        QMetaObject.invokeMethod(
            self._engine,
            "stop_capture",
            Qt.ConnectionType.BlockingQueuedConnection,
        )
        self.on_chunk = None
        self._engine.on_chunk = None
        return b""

    def mark(self):
        self._engine.mark()

    def since_mark(self):
        return self._engine.since_mark()

    @property
    def active(self):
        return self._engine.running

    def _wait_ready(self):
        if self._ready.wait(2):
            return
        raise RuntimeError(messages.MICROPHONE_NOT_OPEN)


def input_devices():
    """Pairs of (id, label). The id is what Settings stores."""
    found = []
    for device in QMediaDevices.audioInputs():
        token = device_token(device)
        if token:
            found.append((token, device.description()))
    return found


def input_device(device_id):
    if device_id:
        for device in QMediaDevices.audioInputs():
            if device_token(device) == device_id:
                return device
    return QMediaDevices.defaultAudioInput()


def device_token(device):
    raw = bytes(device.id())
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="replace")
    if text and not any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return text
    return raw.hex()


def level(pcm):
    if len(pcm) < 2:
        return 0
    total = 0
    count = 0
    for index in range(0, len(pcm) - 1, 8):
        sample = int.from_bytes(pcm[index:index + 2], "little", signed=True)
        total += sample * sample
        count += 1
    if not count:
        return 0
    return (total / count) ** 0.5
