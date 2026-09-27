from PyQt6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices

from . import messages


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
        if self._io is not None:
            self._read()
            self._io = None
        if self._source is not None:
            self._source.stop()
            self._source = None
        pcm = b"".join(self._chunks)
        self._chunks = []
        return pcm

    @property
    def active(self):
        return self._source is not None
