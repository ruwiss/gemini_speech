from PyQt6.QtCore import QTimer
from PyQt6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices

from . import messages

RATE = 16000
WIDTH = 2


class Recorder:
    def __init__(self):
        self._source = None
        self._io = None
        self._chunks = []
        self._mark = 0
        self.on_chunk = None
        self._pump = QTimer()
        self._pump.setInterval(30)
        self._pump.timeout.connect(self._read)

    def start(self):
        self.stop()
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            raise RuntimeError(messages.NO_MICROPHONE)
        self._source = QAudioSource(device, fmt)
        self._source.setBufferSize(RATE * WIDTH // 25)
        self._io = self._source.start()
        if self._io is None:
            raise RuntimeError(messages.MICROPHONE_NOT_OPEN)
        self._chunks = []
        self._mark = 0
        self._io.readyRead.connect(self._read)
        self._pump.start()

    def mark(self):
        self._mark = sum(len(chunk) for chunk in self._chunks)

    def since_mark(self):
        data = b"".join(self._chunks)
        if self._mark >= len(data):
            return b""
        return data[self._mark:]

    def _read(self):
        if self._io is None:
            return
        data = self._io.readAll()
        if not data:
            return
        blob = bytes(data)
        self._chunks.append(blob)
        if self.on_chunk is not None:
            self.on_chunk(blob)

    def stop(self):
        self._pump.stop()
        source = self._source
        io = self._io
        self._source = None
        self._io = None
        if source is not None:
            source.stop()
        if io is not None:
            data = bytes(io.readAll())
            if data:
                self._chunks.append(data)
                if self.on_chunk is not None:
                    self.on_chunk(data)
        pcm = b"".join(self._chunks)
        self._chunks = []
        return pcm

    @property
    def active(self):
        return self._source is not None


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
