import json
import os
import queue
import sys
import threading
import time

if sys.platform == "win32":
    os.environ["QT_MEDIA_BACKEND"] = "windows"

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap, QColor
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import ffmpeg
from . import hosts
from . import hotkey
from . import indicator
from . import messages
from . import paste
from . import paths
from . import speech
from .audio import Recorder
from .settings import Settings


class _LiveFeed(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        self.sid = None
        self.failed = None
        self._cancelled = False

    def push(self, pcm):
        if pcm and not self._cancelled:
            self.q.put(pcm)

    def cancel(self):
        self._cancelled = True
        self._drain()
        self.q.put(None)

    def close_input(self):
        self.q.put(None)
        self.join(timeout=30)

    def _drain(self):
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                return

    def run(self):
        sid = None
        try:
            from .crashlog import note
            note("live start")
            sid = speech.live_start()
            note("live ready")
        except Exception as exc:
            from .crashlog import note
            note("live failed %s" % exc)
            self.failed = exc
            return
        if self._cancelled:
            speech.live_cancel(sid)
            return
        self.sid = sid
        buf = bytearray()
        stopping = False
        try:
            while not self._cancelled and not stopping:
                item = self.q.get()
                if item is None:
                    stopping = True
                else:
                    buf.extend(item)
                    while True:
                        try:
                            extra = self.q.get_nowait()
                        except queue.Empty:
                            break
                        if extra is None:
                            stopping = True
                            break
                        buf.extend(extra)
                if not buf or self._cancelled:
                    continue
                if stopping or len(buf) >= 6400:
                    speech.live_write(sid, bytes(buf))
                    buf.clear()
        except Exception as exc:
            self.failed = exc
        finally:
            buf.clear()
        if self._cancelled:
            speech.live_cancel(sid)
            self.sid = None


class _Finish(QThread):
    text_ready = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, live, pcm):
        super().__init__()
        self._live = live
        self._pcm = pcm

    def run(self):
        live = self._live
        pcm = self._pcm
        self._live = None
        self._pcm = b""
        try:
            if live is not None:
                live.close_input()
                if live.sid and not live.failed:
                    pcm = b""
                    text = speech.live_finish(live.sid)
                    live.sid = None
                    self.text_ready.emit(text)
                    return
                if live.sid:
                    speech.live_cancel(live.sid)
                    live.sid = None
            self.text_ready.emit(speech.transcribe(pcm))
        except Exception as exc:
            if live is not None and live.sid:
                speech.live_cancel(live.sid)
                live.sid = None
            self.failed.emit(str(exc)[:80])


def _qt_log(mode, _context, message):
    from .crashlog import note
    note("qt %s: %s" % (mode, message))


def main():
    from PyQt6.QtCore import Qt, qInstallMessageHandler
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    qInstallMessageHandler(_qt_log)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    GeminiSpeech().start()
    sys.exit(app.exec())


class GeminiSpeech:
    def __init__(self):
        self.shortcut = ""
        self.cancel = "Esc"
        self.setup_done = False
        self.server = speech.Server()
        self.recorder = Recorder()
        self.indicator = indicator.Indicator()
        self.keys = hotkey.Hotkey()
        self.keys.failed.connect(self._fail)
        self.settings = Settings(self.save_shortcut, self._settings_closed)
        self._quitting = False
        self.busy = False
        self._job = None
        self._live = None
        self._load()
        self.tray = QSystemTrayIcon(self._dot(False))
        QApplication.instance().setWindowIcon(QIcon(paths.ICON))
        self.tray.setToolTip("Gemini Speech")
        self.menu = QMenu()
        settings = QAction("Settings", self.menu)
        settings.triggered.connect(self.show_settings)
        quit_ = QAction("Quit", self.menu)
        quit_.triggered.connect(self.quit)
        self.menu.addAction(settings)
        self.menu.addAction(quit_)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.watch = QTimer()
        self.watch.setInterval(2000)
        self.watch.timeout.connect(self.refresh)
        self.cancel_watch = QTimer()
        self.cancel_watch.setInterval(40)
        self.cancel_watch.timeout.connect(self._watch_cancel)

    def start(self):
        QApplication.instance().aboutToQuit.connect(self.server.stop)
        hosts.install()
        try:
            self.server.start()
        except Exception as exc:
            self._fail(str(exc))
        if self.shortcut:
            self.keys.start(self.shortcut)
        self.tray.show()
        self.watch.start()
        self.cancel_watch.start()
        self.refresh()
        if not self.setup_done or not ffmpeg.available():
            self.show_settings()

    def show_settings(self):
        self.keys.stop()
        self.settings.set_values(self.shortcut, self.cancel)
        self.settings.refresh(self.setup_done)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def _settings_closed(self):
        if self._quitting:
            return
        if self.shortcut:
            self.keys.start(self.shortcut)
        else:
            self.keys.stop()

    def _arm_shortcut(self):
        if self.settings.isVisible():
            self.keys.stop()
            return
        if self.shortcut:
            self.keys.start(self.shortcut)
        else:
            self.keys.stop()

    def save_shortcut(self, record, cancel):
        self.shortcut = record
        self.cancel = cancel
        self._store()
        self.shortcut_owned(record, cancel)
        self._arm_shortcut()
        self.settings.refresh(self.setup_done)

    def shortcut_owned(self, record, cancel):
        self.settings.shortcut.owned = record
        self.settings.cancel.owned = cancel

    def toggle(self):
        from .crashlog import note
        if self.busy or self.settings.isVisible():
            note("toggle skipped")
            return
        if self.recorder.active:
            self._finish()
            return
        if not ffmpeg.available():
            note("toggle no ffmpeg")
            self._overlay("error", messages.INSTALL_FFMPEG)
            self.show_settings()
            return
        if not speech.cookies_ready():
            age = 0
            if os.path.exists(paths.cookies_path()):
                age = int(time.time() - os.path.getmtime(paths.cookies_path()))
            note("toggle no cookie age %s" % age)
            if speech.cookies_known() or self.setup_done:
                self._overlay("error", messages.COOKIE_EXPIRED)
            else:
                self._overlay("error", messages.EXTENSION_MISSING)
                self.show_settings()
            return
        self._live = _LiveFeed()
        self._live.start()
        self.recorder.on_chunk = self._live.push
        try:
            from .crashlog import note
            note("opening microphone")
            self.recorder.start()
            note("microphone open")
            self._overlay("recording")
            note("indicator shown")
        except Exception as exc:
            self._drop_recording()
            self._overlay("error", str(exc)[:80])
            return
        self._sync_tray()
        note("toggle returned")

    def _finish(self):
        pcm = self.recorder.stop()
        self.recorder.on_chunk = None
        live = self._live
        self._live = None
        self._sync_tray()
        self._overlay("busy")
        self.busy = True
        job = _Finish(live, pcm)
        job.text_ready.connect(self._pasted)
        job.failed.connect(self._transcribe_failed)
        job.finished.connect(job.deleteLater)
        self._job = job
        job.start()

    def _drop_recording(self):
        self.recorder.on_chunk = None
        self.recorder.stop()
        live = self._live
        self._live = None
        if live is not None:
            live.cancel()

    def _pasted(self, text):
        self.busy = False
        if not paste.paste_text(text):
            self._overlay("error", messages.NO_SPEECH)
            return
        self._overlay("done")

    def _transcribe_failed(self, message):
        self.busy = False
        self._overlay("error", message)

    def _watch_cancel(self):
        error = self.keys.take_error()
        if error:
            self._fail(error)
        if self.keys.take():
            self.toggle()
        if self.recorder.active and hotkey.held(self.cancel):
            self._drop_recording()
            self.busy = False
            self._sync_tray()
            self._overlay("hide")

    def refresh(self):
        if speech.cookies_ready() and not self.setup_done:
            self.setup_done = True
            self._store()
        ready = speech.healthy() and speech.cookies_ready()
        self.tray.setToolTip("Gemini Speech is ready" if ready else "Gemini Speech: waiting for the extension")
        if self.settings.isVisible():
            self.settings.refresh(self.setup_done)

    def _fail(self, message):
        self._overlay("error", message[:80])

    def quit(self):
        self._quitting = True
        self.keys.stop()
        self._drop_recording()
        self.server.stop()
        QApplication.quit()

    def _activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle()

    def _load(self):
        path = paths.config_path()
        if not os.path.exists(path):
            return
        try:
            data = json.loads(open(path, encoding="utf-8").read())
        except Exception:
            return
        if data.get("shortcut"):
            self.shortcut = data["shortcut"]
        if data.get("cancel"):
            self.cancel = data["cancel"]
        self.setup_done = bool(data.get("setup_done"))

    def _store(self):
        open(paths.config_path(), "w", encoding="utf-8").write(
            json.dumps({
                "shortcut": self.shortcut,
                "cancel": self.cancel,
                "setup_done": self.setup_done,
            }, ensure_ascii=False)
        )

    def _overlay(self, kind, message=""):
        # Showing the overlay in the same event-loop turn as QAudioSource start/stop aborts the frozen build.
        QTimer.singleShot(0, lambda: self._show_overlay(kind, message))

    def _show_overlay(self, kind, message):
        if kind == "recording":
            self.indicator.show_recording()
        elif kind == "busy":
            self.indicator.show_busy()
        elif kind == "done":
            self.indicator.show_done()
        elif kind == "error":
            self.indicator.show_error(message)
        elif kind == "hide":
            self.indicator.dismiss()

    def _sync_tray(self):
        self.tray.setIcon(self._dot(self.recorder.active))

    def _dot(self, listening):
        from PyQt6.QtGui import QPainter
        pix = QPixmap(32, 32)
        pix.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(0, 0, 0, 0))
        painter.setBrush(QColor(240, 78, 82) if listening else QColor(154, 160, 170))
        painter.drawEllipse(8, 8, 16, 16)
        painter.end()
        return QIcon(pix)
