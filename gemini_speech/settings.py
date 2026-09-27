from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QVBoxLayout,
)

from . import __version__
from . import hotkey
from . import messages
from . import paths

LANGUAGES = (
    ("English", "en"),
    ("Turkish", "tr"),
    ("German", "de"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Dutch", "nl"),
    ("Polish", "pl"),
    ("Russian", "ru"),
    ("Ukrainian", "uk"),
    ("Arabic", "ar"),
    ("Chinese", "zh"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
)


class VersionLink(QLabel):
    def __init__(self):
        super().__init__(__version__)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("github.com/ruwiss/gemini_speech")
        self.setStyleSheet("color: #7d8490; font-size: 11px;")

    def mousePressEvent(self, event):
        QDesktopServices.openUrl(QUrl("https://github.com/ruwiss/gemini_speech"))
        event.accept()


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
        self.setWindowTitle("GeminiSpeechAPI")
        self.setWindowIcon(QIcon(paths.ICON))
        self.setMinimumWidth(440)
        self.setStyleSheet(
            "QDialog { background: #17191e; }"
            "QLabel { color: #e7e9ee; font-size: 13px; }"
            "QLineEdit, QComboBox { background: #242830; color: #f2f4f8; border: 1px solid #3c4250;"
            " border-radius: 8px; padding: 8px 10px; }"
            "QComboBox QAbstractItemView { background: #242830; color: #f2f4f8;"
            " selection-background-color: #3b82f6; }"
            "QPushButton { background: #3b82f6; color: white; border: none;"
            " border-radius: 8px; padding: 8px 14px; }"
            "QPushButton:hover { background: #5b97f7; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        form = QFormLayout()
        form.setSpacing(10)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("AI Studio API key")
        self.shortcut = ShortcutField()
        self.translate = ShortcutField()
        self.language = QComboBox()
        for label, code in LANGUAGES:
            self.language.addItem(label, code)
        self.cancel = ShortcutField(allow_bare=True)
        form.addRow("API key", self.api_key)
        form.addRow("Record", self.shortcut)
        form.addRow("Translate", self.translate)
        form.addRow("Language", self.language)
        form.addRow("Cancel", self.cancel)
        self._save_button = QPushButton("Save")
        self._save_button.setAutoDefault(False)
        self._save_button.clicked.connect(self._save)
        form.addRow("", self._save_button)
        layout.addLayout(form)
        hint = QLabel(
            "Record types what you say. Translate types it in the language you pick. "
            "Both shortcuts are optional."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #b7bcc8;")
        layout.addWidget(hint)
        layout.addWidget(VersionLink())

    def set_values(self, api_key, shortcut, translate, language, cancel):
        self.api_key.setText(api_key)
        self.shortcut.owned = shortcut
        self.translate.owned = translate
        self.cancel.owned = cancel
        self.shortcut.setText(shortcut)
        self.translate.setText(translate)
        self.cancel.setText(cancel)
        index = self.language.findData(language)
        self.language.setCurrentIndex(index if index >= 0 else 0)

    def closeEvent(self, event):
        super().closeEvent(event)
        self._on_close()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit)

    def _fit(self):
        layout = self.layout()
        layout.invalidate()
        layout.activate()
        hint = layout.sizeHint()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        height = hint.height()
        self.resize(max(self.minimumWidth(), hint.width()), height)
        self.setFixedHeight(height)

    def _save(self):
        record = self.shortcut.text().strip()
        translate = self.translate.text().strip()
        cancel = self.cancel.text().strip() or "Esc"
        key = self.api_key.text().strip()
        language = self.language.currentData() or "en"
        if record and translate and hotkey.same_shortcut(record, translate):
            QMessageBox.warning(self, messages.SHORTCUT_TITLE, messages.SHORTCUT_SAME)
            return
        if record:
            reason = hotkey.windows_conflict(record, current=self.shortcut.owned)
            if reason:
                QMessageBox.warning(self, messages.SHORTCUT_TITLE, reason)
                return
        if translate:
            reason = hotkey.windows_conflict(translate, current=self.translate.owned)
            if reason:
                QMessageBox.warning(self, messages.SHORTCUT_TITLE, reason)
                return
        cancel_reason = hotkey.windows_conflict(cancel, probe=False, current=self.cancel.owned)
        if cancel_reason:
            QMessageBox.warning(self, messages.SHORTCUT_TITLE, cancel_reason)
            return
        self._on_save(key, record, translate, language, cancel)
        self._save_button.setText("Saved")
        QTimer.singleShot(1500, lambda: self._save_button.setText("Save"))
