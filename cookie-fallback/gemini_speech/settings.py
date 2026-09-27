import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from . import ffmpeg
from . import hotkey
from . import messages
from . import paths
from . import speech


class ShortcutField(QLineEdit):
    _MODS = {
        Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
    }

    def __init__(self, allow_bare=False):
        super().__init__()
        self._allow_bare = allow_bare
        self._capturing = False
        self._previous = ""
        self.setReadOnly(True)
        self.setPlaceholderText("Click, then press the keys")
        self.owned = ""

    def mousePressEvent(self, event):
        self._previous = self.text()
        self._capturing = True
        self.setText("")
        self.setPlaceholderText("Press the keys")
        self.setFocus()
        event.accept()

    def focusOutEvent(self, event):
        if self._capturing:
            self._capturing = False
            self.setText(self._previous)
            self.setPlaceholderText("Click, then press the keys")
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if not self._capturing:
            event.ignore()
            return
        event.accept()
        if event.key() in self._MODS:
            return
        if event.key() == Qt.Key.Key_Escape:
            self._capturing = False
            self.setText(self._previous)
            return
        combo = _combo(event, self._allow_bare)
        if not combo:
            return
        self._capturing = False
        self.setPlaceholderText("Click, then press the keys")
        reason = hotkey.windows_conflict(combo, current=self.owned or self._previous)
        if reason:
            self.setText(self._previous)
            QMessageBox.warning(self.window(), messages.SHORTCUT_TITLE, reason)
            return
        self.setText(combo)


def _combo(event, allow_bare=False):
    mods = event.modifiers()
    parts = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        parts.append("Ctrl")
    if mods & Qt.KeyboardModifier.AltModifier:
        parts.append("Alt")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        parts.append("Shift")
    if mods & Qt.KeyboardModifier.MetaModifier:
        parts.append("Meta")
    key = event.key()
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        name = chr(key)
    elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
        name = "F%d" % (key - Qt.Key.Key_F1 + 1)
    elif key == Qt.Key.Key_Space:
        name = "Space"
    elif key == Qt.Key.Key_Escape:
        name = "Esc"
    else:
        name = ""
    if not name or (not parts and not allow_bare):
        return ""
    return "+".join(parts + [name])


class Settings(QDialog):
    def __init__(self, on_save, on_close):
        super().__init__()
        self._on_save = on_save
        self._on_close = on_close
        self._mode = None
        self.setWindowTitle("Gemini Speech")
        self.setWindowIcon(QIcon(paths.ICON))
        self.setMinimumWidth(440)
        self.setStyleSheet(
            "QDialog { background: #17191e; }"
            "QLabel { color: #e7e9ee; font-size: 13px; }"
            "QLineEdit { background: #242830; color: #f2f4f8; border: 1px solid #3c4250;"
            " border-radius: 8px; padding: 8px 10px; }"
            "QPushButton { background: #3b82f6; color: white; border: none;"
            " border-radius: 8px; padding: 8px 14px; }"
            "QPushButton:hover { background: #5b97f7; }"
            "QPushButton#copy { background: #2c313c; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        self.shortcuts = QWidget()
        form = QFormLayout(self.shortcuts)
        form.setSpacing(10)
        self.shortcut = ShortcutField()
        self.cancel = ShortcutField(allow_bare=True)
        form.addRow("Record", self.shortcut)
        form.addRow("Cancel", self.cancel)
        self._save_button = QPushButton("Save")
        self._save_button.setAutoDefault(False)
        self._save_button.clicked.connect(self._save)
        form.addRow("", self._save_button)
        layout.addWidget(self.shortcuts)
        self.setup = QWidget()
        setup_layout = QVBoxLayout(self.setup)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Install the extension")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        setup_layout.addWidget(title)
        why = QLabel(
            "Speech needs a Google cookie. The extension can read it only while "
            "Brave or Chrome is open. Install it once."
        )
        why.setWordWrap(True)
        why.setStyleSheet("color: #b7bcc8;")
        setup_layout.addWidget(why)
        setup_layout.addWidget(_step("1. Open Brave or Chrome."))
        setup_layout.addWidget(_step("2. Type this in the address bar."))
        setup_layout.addWidget(_copy_line("brave://extensions"))
        setup_layout.addWidget(_step("Chrome instead:"))
        setup_layout.addWidget(_copy_line("chrome://extensions"))
        setup_layout.addWidget(_step("3. Turn on Developer mode, top right."))
        setup_layout.addWidget(_step("4. Click Load unpacked."))
        setup_layout.addWidget(_step("5. Select this folder."))
        setup_layout.addWidget(_copy_line(paths.EXTENSION))
        setup_layout.addWidget(_step("6. Leave the browser open."))
        layout.addWidget(self.setup)
        self.ffmpeg_box = QWidget()
        ffmpeg_layout = QVBoxLayout(self.ffmpeg_box)
        ffmpeg_layout.setContentsMargins(0, 0, 0, 0)
        ffmpeg_title = QLabel("Install ffmpeg")
        ffmpeg_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        ffmpeg_layout.addWidget(ffmpeg_title)
        ffmpeg_why = QLabel(
            "Speech encodes the recording with ffmpeg. Run this once in a terminal. "
            "This window notices when it is installed."
        )
        ffmpeg_why.setWordWrap(True)
        ffmpeg_why.setStyleSheet("color: #b7bcc8;")
        ffmpeg_layout.addWidget(ffmpeg_why)
        ffmpeg_layout.addWidget(_copy_line(ffmpeg.install_command()))
        layout.addWidget(self.ffmpeg_box)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def set_values(self, shortcut, cancel):
        self.shortcut.owned = shortcut
        self.cancel.owned = cancel
        self.shortcut.setText(shortcut)
        self.cancel.setText(cancel)

    def closeEvent(self, event):
        super().closeEvent(event)
        self._on_close()

    def apply_mode(self, ready):
        ffmpeg_ok = ffmpeg.available()
        mode = (ready, ffmpeg_ok)
        changed = self._mode != mode
        self._mode = mode
        self._place(self.shortcuts, ready and ffmpeg_ok)
        self._place(self.setup, not ready)
        self._place(self.ffmpeg_box, not ffmpeg_ok)
        self._place(self.status, not ready or not ffmpeg_ok)
        if changed:
            self._fit()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit)

    def _place(self, widget, shown):
        widget.setVisible(shown)
        if shown:
            widget.setMaximumHeight(16777215)
            widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        else:
            widget.setMaximumHeight(0)
            widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def _fit(self):
        layout = self.layout()
        layout.invalidate()
        layout.activate()
        hint = layout.sizeHint()
        width = max(self.minimumWidth(), hint.width())
        height = hint.height()
        extra = self.height() - height if self.isVisible() else 0
        if 0 < extra <= 40:
            height -= extra
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.resize(width, height)
        self.setFixedHeight(height)

    def refresh(self, ready):
        if not ffmpeg.available():
            self.status.setText("Waiting for ffmpeg.")
        elif not speech.healthy():
            self.status.setText("Speech server is off.")
        elif speech.cookies_ready():
            self.status.setText("Ready.")
        elif speech.cookies_known():
            self.status.setText("Cookie expired. Open the browser.")
        else:
            self.status.setText("Waiting for the cookie.")
        self.apply_mode(ready)

    def _save(self):
        record = self.shortcut.text().strip()
        cancel = self.cancel.text().strip() or "Esc"
        if not record:
            return
        reason = hotkey.windows_conflict(record, current=self.shortcut.owned)
        if reason:
            QMessageBox.warning(self, messages.SHORTCUT_TITLE, reason)
            return
        cancel_reason = hotkey.windows_conflict(cancel, probe=False, current=self.cancel.owned)
        if cancel_reason:
            QMessageBox.warning(self, messages.SHORTCUT_TITLE, cancel_reason)
            return
        self._on_save(record, cancel)
        self._save_button.setText("Saved")
        QTimer.singleShot(1500, lambda: self._save_button.setText("Save"))


def _step(text):
    label = QLabel(text)
    label.setWordWrap(True)
    return label


def _copy_line(value):
    return CopyRow(value)


class CopyRow(QWidget):
    def __init__(self, value):
        super().__init__()
        self._value = value
        line = QLineEdit(value)
        line.setReadOnly(True)
        self.button = QPushButton("Copy")
        self.button.setObjectName("copy")
        self.button.setFixedWidth(72)
        self.button.setAutoDefault(False)
        self.button.clicked.connect(self._copy)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 0, 0)
        row.addWidget(line, 1)
        row.addWidget(self.button)

    def _copy(self):
        if not _copy_text(self._value):
            self.button.setText("Failed")
        else:
            self.button.setText("Copied")
        QTimer.singleShot(900, lambda: self.button.setText("Copy"))


def _copy_text(text):
    if sys.platform != "win32":
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        return True
    import ctypes
    from ctypes import wintypes
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    data = (text + "\0").encode("utf-16-le")
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        locked = kernel32.GlobalLock(handle)
        ctypes.memmove(locked, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
    finally:
        user32.CloseClipboard()
    return True
