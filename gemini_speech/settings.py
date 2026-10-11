from PyQt6.QtCore import Qt, QLocale, QSize, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from . import __version__
from . import dictionary
from . import hotkey
from . import messages
from . import paths

_STYLE = (
    "QDialog { background: #17191e; }"
    "QLabel { color: #e7e9ee; font-size: 13px; }"
    "QLineEdit, QComboBox, QListWidget { background: #242830; color: #f2f4f8;"
    " border: 1px solid #3c4250; border-radius: 8px; padding: 8px 10px; }"
    "QComboBox QAbstractItemView, QListWidget { background: #242830; color: #f2f4f8;"
    " selection-background-color: #3b82f6; }"
    "QListWidget { padding: 4px; }"
    "QListWidget::item { border: none; }"
    "QPushButton { background: #3b82f6; color: white; border: none;"
    " border-radius: 8px; padding: 8px 14px; }"
    "QPushButton:hover { background: #5b97f7; }"
    "QPushButton#secondary { background: #242830; color: #f2f4f8; border: 1px solid #3c4250; }"
    "QPushButton#secondary:hover { background: #2e3440; }"
)


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


def system_language():
    """Preferred language of this device, when the list has it. Otherwise English."""
    known = {item[1] for item in LANGUAGES}
    codes = []
    for name in QLocale.system().uiLanguages():
        code = name.replace("-", "_").split("_")[0].lower()
        if code and code not in codes:
            codes.append(code)
    fallback = QLocale.system().name().replace("-", "_").split("_")[0].lower()
    if fallback and fallback not in codes:
        codes.append(fallback)
    for code in codes:
        if code in known:
            return code
    return "en"


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


class _PairRow(QWidget):
    def __init__(self, match, replacement, on_remove):
        super().__init__()
        self.match = match
        self.replacement = replacement
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)
        heard = QLabel(match)
        heard.setStyleSheet("color: #b7bcc8;")
        arrow = QLabel("→")
        arrow.setStyleSheet("color: #7d8490;")
        written = QLabel(replacement)
        remove = QPushButton("×")
        remove.setObjectName("secondary")
        remove.setFixedSize(28, 28)
        remove.setAutoDefault(False)
        remove.clicked.connect(lambda _checked=False: on_remove())
        layout.addWidget(heard, 1)
        layout.addWidget(arrow)
        layout.addWidget(written, 1)
        layout.addWidget(remove)


class DictionaryWindow(QDialog):
    def __init__(self, pairs, on_change, parent):
        super().__init__(parent)
        self._on_change = on_change
        self._pairs = dictionary.normalize(pairs)
        self.setWindowTitle("Dictionary")
        self.setWindowIcon(QIcon(paths.ICON))
        self.setMinimumSize(460, 390)
        self.resize(460, 390)
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        fields = QHBoxLayout()
        fields.setSpacing(10)
        match_box = QVBoxLayout()
        match_box.setSpacing(6)
        match_box.addWidget(QLabel("Match"))
        self.match = QLineEdit()
        self.match.setPlaceholderText("Word in the transcript")
        self.match.returnPressed.connect(self._add)
        match_box.addWidget(self.match)
        replace_box = QVBoxLayout()
        replace_box.setSpacing(6)
        replace_box.addWidget(QLabel("Replace"))
        self.replacement = QLineEdit()
        self.replacement.setPlaceholderText("Write this instead")
        self.replacement.returnPressed.connect(self._add)
        replace_box.addWidget(self.replacement)
        fields.addLayout(match_box, 1)
        fields.addLayout(replace_box, 1)
        layout.addLayout(fields)
        add = QPushButton("Add")
        add.setAutoDefault(False)
        add.clicked.connect(self._add)
        layout.addWidget(add)
        self.list = QListWidget()
        self.list.setSpacing(2)
        self.list.itemDoubleClicked.connect(self._load_row)
        layout.addWidget(self.list, 1)
        hint = QLabel("Match ignores case. Replace is written exactly as you type it.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #b7bcc8;")
        layout.addWidget(hint)
        self._fill()

    def set_pairs(self, pairs):
        self._pairs = dictionary.normalize(pairs)
        self._fill()

    def _add(self):
        match = " ".join(self.match.text().split())
        replacement = " ".join(self.replacement.text().split())
        if not match or not replacement:
            return
        self._pairs = dictionary.normalize(self._pairs + [(match, replacement)])
        self.match.clear()
        self.replacement.clear()
        self.match.setFocus()
        self._fill()
        self._on_change(self._pairs)

    def _remove(self, match):
        self._pairs = [pair for pair in self._pairs if not dictionary.same(pair[0], match)]
        self._fill()
        self._on_change(self._pairs)

    def _load_row(self, item):
        row = self.list.itemWidget(item)
        if row is None:
            return
        self.match.setText(row.match)
        self.replacement.setText(row.replacement)
        self.replacement.setFocus()

    def _fill(self):
        self.list.clear()
        for match, replacement in self._pairs:
            item = QListWidgetItem()
            row = _PairRow(match, replacement, lambda match=match: self._remove(match))
            item.setSizeHint(QSize(0, 36))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)


class Settings(QDialog):
    def __init__(self, on_save, on_close, on_dictionary):
        super().__init__()
        self._on_save = on_save
        self._on_close = on_close
        self._on_dictionary = on_dictionary
        self._pairs = []
        self._dictionary_window = None
        self.setWindowTitle("GeminiSpeechAPI")
        self.setWindowIcon(QIcon(paths.ICON))
        self.setMinimumWidth(440)
        self.setStyleSheet(_STYLE)
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
        self.style = QComboBox()
        self.style.addItem("Press to toggle", "toggle")
        self.style.addItem("Hold to talk", "hold")
        self.language = QComboBox()
        for label, code in LANGUAGES:
            self.language.addItem(label, code)
        self.transcription = QComboBox()
        self.transcription.addItem("Smart", "smart")
        self.transcription.addItem("Verbatim", "verbatim")
        self.microphone = QComboBox()
        self.microphone.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.microphone.setMinimumContentsLength(18)
        self._microphone_id = ""
        self.cancel = ShortcutField(allow_bare=True)
        self._dictionary_button = QPushButton("Open")
        self._dictionary_button.setObjectName("secondary")
        self._dictionary_button.setAutoDefault(False)
        self._dictionary_button.clicked.connect(self._open_dictionary)
        form.addRow("API key", self.api_key)
        form.addRow("Record", self.shortcut)
        form.addRow("Translate", self.translate)
        form.addRow("Keys", self.style)
        form.addRow("Language", self.language)
        form.addRow("Transcript", self.transcription)
        form.addRow("Microphone", self.microphone)
        form.addRow("Cancel", self.cancel)
        form.addRow("Dictionary", self._dictionary_button)
        self._save_button = QPushButton("Save")
        self._save_button.setAutoDefault(False)
        self._save_button.clicked.connect(self._save)
        form.addRow("", self._save_button)
        layout.addLayout(form)
        hint = QLabel(
            "Hold to talk records while the shortcut is down. Press to toggle starts and stops. "
            "Smart drops filler words. Verbatim keeps every word."
        )
        hint.setWordWrap(True)
        hint.setFixedWidth(396)
        hint.setStyleSheet("color: #b7bcc8;")
        layout.addWidget(hint)
        layout.addWidget(VersionLink())

    def set_values(self, api_key, shortcut, translate, language, cancel, dictionary_words, style, transcription, microphone):
        self.api_key.setText(api_key)
        self.shortcut.owned = shortcut
        self.translate.owned = translate
        self.cancel.owned = cancel
        self.shortcut.setText(shortcut)
        self.translate.setText(translate)
        self.cancel.setText(cancel)
        index = self.language.findData(language)
        self.language.setCurrentIndex(index if index >= 0 else 0)
        style_index = self.style.findData(style if style in ("hold", "toggle") else "toggle")
        self.style.setCurrentIndex(style_index if style_index >= 0 else 0)
        transcript_index = self.transcription.findData(transcription if transcription in ("smart", "verbatim") else "smart")
        self.transcription.setCurrentIndex(transcript_index if transcript_index >= 0 else 0)
        self._microphone_id = microphone or ""
        self._fill_mics(self._microphone_id)
        self._pairs = dictionary.normalize(dictionary_words)
        self._refresh_dictionary_button()
        if self._dictionary_window is not None:
            self._dictionary_window.set_pairs(self._pairs)

    def showEvent(self, event):
        self._fill_mics(self.microphone.currentData() or self._microphone_id)
        super().showEvent(event)
        QTimer.singleShot(0, self._fit)

    def _fill_mics(self, selected):
        from .audio import input_devices
        self.microphone.blockSignals(True)
        self.microphone.clear()
        self.microphone.addItem("System default", "")
        chosen = 0
        for token, label in input_devices():
            self.microphone.addItem(label, token)
            if selected and token == selected:
                chosen = self.microphone.count() - 1
        if selected and chosen == 0:
            self.microphone.addItem("Saved microphone (unplugged)", selected)
            chosen = self.microphone.count() - 1
        self.microphone.setCurrentIndex(chosen)
        self.microphone.blockSignals(False)

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
        language = self.language.currentData() or system_language()
        style = self.style.currentData() or "toggle"
        if style not in ("hold", "toggle"):
            style = "toggle"
        transcription = self.transcription.currentData() or "smart"
        if transcription not in ("smart", "verbatim"):
            transcription = "smart"
        microphone = self.microphone.currentData() or ""
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
        self._microphone_id = microphone
        self._on_save(key, record, translate, language, cancel, self._pairs, style, transcription, microphone)
        self._save_button.setText("Saved")
        QTimer.singleShot(1500, lambda: self._save_button.setText("Save"))

    def closeEvent(self, event):
        if self._dictionary_window is not None:
            self._dictionary_window.close()
        super().closeEvent(event)
        self._on_close()

    def _open_dictionary(self):
        window = self._dictionary_window
        if window is None:
            window = DictionaryWindow(self._pairs, self._dictionary_changed, self)
            self._dictionary_window = window
        else:
            window.set_pairs(self._pairs)
        window.show()
        window.raise_()
        window.activateWindow()
        window.match.setFocus()

    def _dictionary_changed(self, pairs):
        self._pairs = dictionary.normalize(pairs)
        self._refresh_dictionary_button()
        self._on_dictionary(self._pairs)

    def _refresh_dictionary_button(self):
        count = len(self._pairs)
        if count == 0:
            self._dictionary_button.setText("Open")
        elif count == 1:
            self._dictionary_button.setText("Open · 1 word")
        else:
            self._dictionary_button.setText("Open · %d words" % count)
