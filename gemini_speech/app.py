import json
import os
import sys

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap, QColor
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import hotkey
from . import indicator
from . import messages
from . import paste
from . import paths
from . import speech
from .audio import Recorder, level
from .settings import Settings


class _Update(QThread):
    ready = pyqtSignal(str)

    def run(self):
        try:
            from . import update
            path = update.download()
        except Exception:
            path = ""
        if path:
            self.ready.emit(path)


class _Finish(QThread):
    text_ready = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, live):
        super().__init__()
        self._live = live

    def run(self):
        live = self._live
        self._live = None
        try:
            self.text_ready.emit(live.finish())
        except Exception as exc:
            self.failed.emit(str(exc)[:80])


def _qt_log(mode, _context, message):
    from .crashlog import note
    note("qt %s: %s" % (mode, message))


def main():
    from PyQt6.QtCore import Qt, qInstallMessageHandler
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GeminiSpeech.GeminiSpeechAPI")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    qInstallMessageHandler(_qt_log)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    GeminiSpeech().start()
    sys.exit(app.exec())


class GeminiSpeech(QObject):
    def __init__(self):
        super().__init__()
        self.shortcut = "Alt+Z"
        self.translate = ""
        self.language = "en"
        self.cancel = "Esc"
        self.api_key = ""
        self.recorder = Recorder()
        self.indicator = indicator.Indicator()
        self.keys = hotkey.Hotkey()
        self.keys.failed.connect(self._fail)
        self.settings = Settings(self.save_settings, self._settings_closed)
        self._quitting = False
        self.busy = False
        self._job = None
        self._live = None
        self._warm = None
        self._rewarm_at = 0.0
        self._stopping = False
        self._finish_token = 0
        self._updating = False
        self._load()
        self.tray = QSystemTrayIcon(self._dot(False))
        QApplication.instance().setWindowIcon(QIcon(paths.ICON))
        self.tray.setToolTip("GeminiSpeechAPI")
        self.menu = QMenu()
        settings = QAction("Settings", self.menu)
        settings.triggered.connect(self.show_settings)
        quit_ = QAction("Quit", self.menu)
        quit_.triggered.connect(self.quit)
        self.menu.addAction(settings)
        self.menu.addAction(quit_)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.cancel_watch = QTimer()
        self.cancel_watch.setInterval(40)
        self.cancel_watch.timeout.connect(self._watch_cancel)

    def start(self):
        self._arm_shortcut()
        from .crashlog import note
        note("tray shown")
        QTimer.singleShot(0, self.tray.show)
        self.cancel_watch.start()
        self._sync_tip()
        self._ensure_warm()
        QTimer.singleShot(4000, self._check_update)
        self._update_timer = QTimer()
        self._update_timer.setInterval(6 * 60 * 60 * 1000)
        self._update_timer.timeout.connect(self._check_update)
        self._update_timer.start()
        if not self.api_key:
            self.show_settings()

    def _check_update(self):
        if self._updating or self._quitting or self.recorder.active or self.busy:
            return
        self._updating = True
        job = _Update()
        job.ready.connect(self._apply_update, Qt.ConnectionType.QueuedConnection)
        job.finished.connect(self._update_finished)
        job.finished.connect(job.deleteLater)
        self._update_job = job
        job.start()

    def _update_finished(self):
        self._updating = False

    def _apply_update(self, path):
        if self._quitting or self.recorder.active or self.busy or not path:
            return
        self.tray.showMessage("GeminiSpeechAPI", "Updating to the latest version", QSystemTrayIcon.MessageIcon.Information, 3000)
        from . import update
        update.launch(path)

    def show_settings(self):
        self.keys.stop()
        self.settings.set_values(self.api_key, self.shortcut, self.translate, self.language, self.cancel)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def _settings_closed(self):
        if self._quitting:
            return
        self._arm_shortcut()
        self._sync_tip()

    def _arm_shortcut(self):
        if self.settings.isVisible():
            self.keys.stop()
            return
        if self.shortcut or self.translate:
            self.keys.start(self.shortcut, self.translate)
        else:
            self.keys.stop()

    def save_settings(self, api_key, record, translate, language, cancel):
        self.api_key = api_key.strip()
        self.shortcut = record
        self.translate = translate
        self.language = language or "en"
        self.cancel = cancel or "Esc"
        self._store()
        self.settings.shortcut.owned = record
        self.settings.translate.owned = translate
        self.settings.cancel.owned = cancel
        self._arm_shortcut()
        self._sync_tip()
        self._ensure_warm()

    def _ensure_warm(self):
        if self._quitting or not self.api_key or self._live is not None:
            return
        warm = self._warm
        if warm is not None and warm.fresh() and warm._key == self.api_key and not warm._language:
            return
        if warm is not None:
            warm.cancel()
        self._warm = speech.LiveSession(self.api_key)
        self._warm.open()

    def _take_live(self):
        warm = self._warm
        self._warm = None
        if warm is None or not warm.fresh():
            if warm is not None:
                warm.cancel()
            warm = speech.LiveSession(self.api_key)
            warm.open()
        return warm

    def toggle(self, mode="record"):
        from .crashlog import note
        if self.busy or self.settings.isVisible():
            note("toggle skipped")
            return
        if self.recorder.active:
            self._finish()
            return
        if not self.api_key:
            note("toggle no api key")
            self._overlay("error", messages.API_KEY_MISSING)
            self.show_settings()
            return
        try:
            note("opening live session")
            if mode == "translate":
                self._live = speech.LiveSession(self.api_key, self.language)
                self._live.open()
            else:
                self._live = self._take_live()
            self.recorder.on_chunk = self._live.push
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
        if self._stopping or self.busy:
            return
        self._stopping = True
        self.busy = True
        self._overlay("busy")
        self._finish_token += 1
        token = self._finish_token
        self.recorder.mark()
        self._tail_quiet = 0
        self._tail_started = __import__("time").monotonic()
        QTimer.singleShot(40, lambda: self._watch_tail(token))

    def _watch_tail(self, token):
        if token != self._finish_token or self._quitting or not self.recorder.active:
            return
        elapsed = __import__("time").monotonic() - self._tail_started
        tail = self.recorder.since_mark()
        recent = tail[-int(0.08 * 32000):]
        if level(recent) >= 400:
            self._tail_quiet = 0
        else:
            self._tail_quiet += 40
        # The last word can still be in the driver. Keep it if it arrives, then stop at the quiet.
        if elapsed >= 0.7 or (elapsed >= 0.22 and self._tail_quiet >= 160):
            self._finish_capture(token)
            return
        QTimer.singleShot(40, lambda: self._watch_tail(token))

    def _finish_capture(self, token):
        if token != self._finish_token or self._quitting:
            return
        self.recorder.stop()
        self.recorder.on_chunk = None
        live = self._live
        self._live = None
        self._stopping = False
        self._sync_tray()
        if live is None:
            self.busy = False
            return
        job = _Finish(live)
        job.text_ready.connect(self._pasted, Qt.ConnectionType.QueuedConnection)
        job.failed.connect(self._transcribe_failed, Qt.ConnectionType.QueuedConnection)
        job.finished.connect(job.deleteLater)
        self._job = job
        job.start()

    def _drop_recording(self):
        self._finish_token += 1
        self._stopping = False
        self.recorder.on_chunk = None
        self.recorder.stop()
        live = self._live
        self._live = None
        if live is not None:
            live.cancel()

    def _pasted(self, text):
        self.busy = False
        self._ensure_warm()
        if not paste.paste_text(text):
            self._overlay("error", messages.NO_SPEECH)
            return
        self._overlay("done")

    def _transcribe_failed(self, message):
        self.busy = False
        self._ensure_warm()
        self._overlay("error", message)

    def _watch_cancel(self):
        error = self.keys.take_error()
        if error:
            self._fail(error)
        action = self.keys.take()
        if action:
            self.toggle(action)
        if (self.recorder.active or self._stopping) and hotkey.held(self.cancel):
            self._drop_recording()
            self.busy = False
            self._sync_tray()
            self._overlay("hide")
            self._ensure_warm()
            return
        if self._live is None and (self._warm is None or self._warm.done.is_set()):
            import time
            if time.monotonic() - self._rewarm_at > 2:
                self._rewarm_at = time.monotonic()
                self._ensure_warm()
        live = self._live
        if self.recorder.active and live is not None and not self.busy and live.done.is_set():
            if live.text.strip() or live.limit_hit.is_set():
                self._finish()
            else:
                message = live.error or messages.REQUEST_FAILED
                self._drop_recording()
                self._overlay("error", message)

    def _sync_tip(self):
        if self.api_key:
            self.tray.setToolTip("GeminiSpeechAPI is ready")
        else:
            self.tray.setToolTip("GeminiSpeechAPI: add an API key")

    def _fail(self, message):
        self._overlay("error", message[:80])

    def quit(self):
        self._quitting = True
        self.keys.stop()
        self._drop_recording()
        if self._warm is not None:
            self._warm.cancel()
            self._warm = None
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
        if "shortcut" in data:
            self.shortcut = data.get("shortcut") or ""
        if "translate" in data:
            self.translate = data.get("translate") or ""
        if data.get("language"):
            self.language = data["language"]
        if data.get("cancel"):
            self.cancel = data["cancel"]
        if data.get("api_key"):
            self.api_key = data["api_key"]

    def _store(self):
        os.makedirs(os.path.dirname(paths.config_path()), exist_ok=True)
        open(paths.config_path(), "w", encoding="utf-8").write(
            json.dumps({
                "api_key": self.api_key,
                "shortcut": self.shortcut,
                "translate": self.translate,
                "language": self.language,
                "cancel": self.cancel,
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
