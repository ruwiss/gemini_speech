from PyQt6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices

from . import messages

RATE = 16000
WIDTH = 2


class Recorder:
    def __init__(self):
        self._source = None
        self._io = None
        self._chunks = []
        self.on_chunk = None

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
        self._io.readyRead.connect(self._read)

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
