import difflib
import math
import sys
import time

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QFontMetrics, QFontMetricsF,
    QLinearGradient,
)
from PyQt6.QtWidgets import QWidget, QApplication

from . import desktop

ICON = 28
GAP = 8
LINE = 36
PAD_X = 30
PAD_R = 14
WORD_GAP = 5
MAX_LINE = 347
ENTER = 0.22
CORRECT = 0.18
WIDTH_TAU = 0.12
INK = QColor(236, 238, 242)
REC = QColor(240, 78, 82)
OK = QColor(80, 205, 140)
ERR = QColor(240, 100, 90)
BUSY = QColor(120, 170, 255)
BG = QColor(22, 24, 29, 230)


def _smooth(amount):
    amount = max(0.0, min(1.0, amount))
    return amount * amount * (3.0 - 2.0 * amount)


class _CaptionWord:
    def __init__(self, text):
        self.text = text
        self.outgoing = ""
        self.opacity = 0.0
        self.out_opacity = 0.0
        self.width = 0.0
        self.target_width = 0.0
        self.x = 0.0
        self.y = 2.6
        self.fade = 0.0
        self.fading = True
        self.retiring = False
        self.fade_for = ENTER


class Indicator(QWidget):
    def __init__(self):
        super().__init__(None)
        # Windows can chase the pointer. macOS hides a tool window while the
        # tray app is inactive, and Wayland will not let a client park a window
        # on the cursor, so those two keep a bar on the screen instead.
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if sys.platform == "win32":
            flags |= Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
        elif sys.platform == "darwin":
            flags |= Qt.WindowType.Tool
        elif not desktop.wayland():
            flags |= Qt.WindowType.Tool | Qt.WindowType.BypassWindowManagerHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle(desktop.OVERLAY_TITLE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(ICON, ICON)
        self._state = ""
        self._message = ""
        self._phase = 0.0
        self._area = None
        self._words = []
        self._line = ""
        self._dropped = 0
        self._scroll = 0.0
        self._scroll_target = 0.0
        self._content = 0.0
        self._anim_at = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self.dismiss)

    def show_recording(self, text=""):
        text = " ".join((text or "").split())
        active = self._state == "recording" and self.isVisible()
        if active and text == self._line:
            return
        if self._state != "recording":
            self._words = []
            self._dropped = 0
            self._scroll = 0.0
            self._scroll_target = 0.0
            self._content = 0.0
            self._anim_at = 0.0
        self._line = text
        self._state = "recording"
        self._message = text
        self._sync_words(text)
        self._animate(0.0)
        if not text and not self._words:
            self._show("recording", "", ICON, ICON)
            return
        if not active:
            self._place()
            if not self.isVisible():
                self.show()
            self._timer.setInterval(33)
            if not self._timer.isActive():
                self._timer.start()
            self._hide.stop()
        else:
            self._place()
        self.update()

    def _caption_font(self):
        font = QFont(self.font())
        font.setPixelSize(14)
        font.setWeight(QFont.Weight.Medium)
        return font

    def show_busy(self):
        self._show("busy", "", ICON, ICON)

    def show_done(self):
        self._show("done", "", ICON, ICON, 700)

    def show_error(self, message):
        metrics = QFontMetrics(self.font())
        text_width = min(420, metrics.horizontalAdvance(message))
        shown = metrics.elidedText(message, Qt.TextElideMode.ElideRight, text_width)
        width = 32 + metrics.horizontalAdvance(shown)
        self._show("error", shown, max(ICON, width), 26, 4000)

    def dismiss(self):
        self._timer.stop()
        self._hide.stop()
        self._state = ""
        self._words = []
        self._line = ""
        self._dropped = 0
        self._scroll = 0.0
        self._scroll_target = 0.0
        self.hide()
        desktop.overlay_hidden()

    def _show(self, state, message, width, height, msec=0):
        self._state = state
        self._message = message
        if state != "recording":
            self._words = []
            self._line = ""
            self._dropped = 0
            self._scroll = 0.0
            self._scroll_target = 0.0
            self._content = 0.0
        self.resize(width, height)
        self._place()
        if not self.isVisible():
            self.show()
        self._timer.setInterval(33)
        if not self._timer.isActive():
            self._timer.start()
        self._hide.stop()
        if msec:
            self._hide.start(msec)
        self.update()

    def _place(self):
        if sys.platform != "win32":
            self._anchor()
            return
        if desktop.place(self):
            return
        pos = QCursor.pos()
        x = pos.x() + GAP
        if self._state == "recording" and self._message:
            y = pos.y() - self.height() - GAP
        else:
            y = pos.y() - self.height() // 2
        area = self._area
        if area is None or not area.contains(pos):
            screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
            area = screen.availableGeometry() if screen else None
            self._area = area
        if area is not None:
            x = max(area.left(), min(x, area.right() - self.width() + 1))
            y = max(area.top(), min(y, area.bottom() - self.height() + 1))
        point = QPointF(x, y).toPoint()
        if self.pos() != point:
            self.move(point)

    def _anchor(self):
        if desktop.place(self):
            return
        pos = QCursor.pos()
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        if area is None:
            return
        # X11 and macOS already shrink this rect around the panel and the Dock.
        # Other Wayland compositors usually do not, so leave room for a bar.
        margin = 24 if sys.platform == "darwin" or not desktop.wayland() else 64
        x = area.left() + max(0, (area.width() - self.width()) // 2)
        y = area.bottom() - self.height() - margin + 1
        x = max(area.left(), min(x, area.right() - self.width() + 1))
        y = max(area.top(), min(y, area.bottom() - self.height() + 1))
        point = QPointF(x, y).toPoint()
        if self.pos() != point:
            self.move(point)

    def _tick(self):
        now = time.monotonic()
        dt = 0.033 if not self._anim_at else min(0.05, max(0.0, now - self._anim_at))
        self._anim_at = now
        self._phase += 0.36
        if self._state == "recording":
            self._animate(dt)
        self._place()
        if self._state in ("recording", "busy"):
            self.update()

    def _measure(self, text):
        if not text:
            return 0.0
        return float(QFontMetricsF(self._caption_font()).horizontalAdvance(text))

    def _move(self, current, target, dt, tau):
        if dt <= 0.0:
            return current
        if abs(target - current) <= 0.2:
            return target
        rate = 1.0 - math.exp(-dt / tau)
        nxt = current + (target - current) * rate
        if abs(target - nxt) <= 0.2:
            return target
        return nxt

    def _sync_words(self, text):
        fresh = text.split() if text else []
        if self._dropped > len(fresh):
            self._dropped = 0
            self._words = [word for word in self._words if word.retiring]
        fresh = fresh[self._dropped:]
        live = [word for word in self._words if not word.retiring]
        old = [word.text for word in live]
        if old == fresh:
            return
        anchors = {}
        for index, word in enumerate(self._words):
            if word.retiring:
                anchors[word] = next((item for item in self._words[index + 1:] if not item.retiring), None)
        matcher = difflib.SequenceMatcher(a=old, b=fresh, autojunk=False)
        rebuilt = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                rebuilt.extend(live[i1:i2])
            elif tag == "insert":
                rebuilt.extend(self._make_word(token) for token in fresh[j1:j2])
            elif tag == "delete":
                for word in live[i1:i2]:
                    word.retiring = True
                    rebuilt.append(word)
            else:
                shared = min(i2 - i1, j2 - j1)
                for offset in range(shared):
                    word = live[i1 + offset]
                    self._retarget(word, fresh[j1 + offset])
                    rebuilt.append(word)
                for word in live[i1 + shared:i2]:
                    word.retiring = True
                    rebuilt.append(word)
                rebuilt.extend(self._make_word(token) for token in fresh[j1 + shared:j2])
        for word, nxt in anchors.items():
            if word in rebuilt:
                continue
            if nxt is not None and nxt in rebuilt:
                rebuilt.insert(rebuilt.index(nxt), word)
            else:
                rebuilt.append(word)
        self._words = rebuilt

    def _make_word(self, text):
        word = _CaptionWord(text)
        word.target_width = self._measure(text)
        return word

    def _retarget(self, word, text):
        if word.text == text:
            return
        previous = word.text
        old_fold = previous.casefold()
        new_fold = text.casefold()
        word.target_width = self._measure(text)
        # A growing or shrinking hypothesis ("hel" -> "hello") stays in place.
        # A real rewrite crossfades so the surrounding words only slide.
        if new_fold.startswith(old_fold) or old_fold.startswith(new_fold):
            word.text = text
            return
        word.outgoing = previous
        word.out_opacity = 1.0
        word.text = text
        word.opacity = 0.0
        word.fade = 0.0
        word.fading = True
        word.fade_for = CORRECT
        word.y = 0.0

    def _snap_tail(self):
        # New words at the end take their real width immediately and fade in.
        # The line scrolls toward them, so a long utterance glides instead of
        # jumping or revealing letter by letter.
        for word in reversed(self._words):
            if word.retiring:
                continue
            if not (word.fading and not word.outgoing):
                break
            word.width = word.target_width

    def _layout(self):
        total = 0.0
        previous = False
        for word in self._words:
            if word.width > 0.25 and previous:
                total += WORD_GAP
            word.x = total
            total += word.width if word.width > 0.0 else 0.0
            if word.width > 0.25:
                previous = True
        self._content = total

    def _max_width(self):
        cap = MAX_LINE
        area = self._area
        if area is not None:
            cap = min(cap, max(220, area.width() - 32))
        return float(cap)

    def _animate(self, dt):
        self._words = [
            word for word in self._words
            if not (
                word.retiring
                and word.width <= 0.4
                and word.opacity <= 0.04
                and word.out_opacity <= 0.04
            )
        ]
        for word in self._words:
            if word.retiring:
                word.target_width = 0.0
                word.opacity = self._move(word.opacity, 0.0, dt, 0.09)
                word.out_opacity = self._move(word.out_opacity, 0.0, dt, 0.09)
                word.y = self._move(word.y, 1.5, dt, 0.1)
            else:
                word.target_width = self._measure(word.text)
                if word.fading:
                    word.fade += dt
                    word.opacity = _smooth(word.fade / word.fade_for) if dt > 0.0 else word.opacity
                    if word.outgoing:
                        word.out_opacity = 1.0 - word.opacity
                        word.y = 0.0
                    else:
                        word.y = 2.6 * (1.0 - word.opacity)
                    if word.opacity >= 0.999:
                        word.fading = False
                        word.opacity = 1.0
                        word.out_opacity = 0.0
                        word.outgoing = ""
                        word.y = 0.0
                else:
                    word.opacity = 1.0
                    word.out_opacity = 0.0
                    word.y = 0.0
            if word.fading and not word.outgoing and not word.retiring:
                width_tau = 0.08
            elif word.outgoing or word.retiring:
                width_tau = 0.16
            else:
                width_tau = WIDTH_TAU
            word.width = self._move(word.width, word.target_width, dt, width_tau)
        self._snap_tail()
        self._layout()
        self._fit_line()
        self._scroll_target = max(0.0, self._content - self._view())
        if self._scroll_target < 1.0:
            self._scroll_target = 0.0
            self._scroll = 0.0
        elif dt > 0.0:
            nudged = self._move(self._scroll, self._scroll_target, dt, 0.16)
            # Keep a burst of words from throwing the line faster than the eye follows.
            cap = 22.0 * (dt / 0.033)
            delta = nudged - self._scroll
            if abs(delta) > cap:
                nudged = self._scroll + (cap if delta > 0.0 else -cap)
            self._scroll = nudged
        self._prune()

    def _view(self):
        return max(1.0, float(self.width()) - PAD_X - PAD_R)

    def _fit_line(self):
        if self._words or self._line:
            width = min(self._max_width(), max(float(ICON), PAD_X + self._content + PAD_R))
            height = float(LINE)
        else:
            width = float(ICON)
            height = float(ICON)
        fitted_w = max(ICON, int(round(width)))
        fitted_h = max(ICON, int(round(height)))
        if self.width() != fitted_w or self.height() != fitted_h:
            self.resize(fitted_w, fitted_h)

    def _prune(self):
        changed = False
        lag = self._scroll_target - self._scroll
        while self._words:
            word = self._words[0]
            live = sum(1 for item in self._words if not item.retiring)
            settled = (
                not word.retiring
                and not word.fading
                and not word.outgoing
                and abs(word.width - word.target_width) < 0.6
            )
            offscreen = word.x + word.width < self._scroll - 24
            if not (settled and offscreen and live > 24):
                break
            self._words.pop(0)
            self._dropped += 1
            changed = True
        if changed:
            self._layout()
            self._fit_line()
            self._scroll_target = max(0.0, self._content - self._view())
            self._scroll = min(self._scroll_target, max(0.0, self._scroll_target - lag))

    def _paint_line(self, painter):
        font = self._caption_font()
        metrics = QFontMetrics(font)
        painter.setFont(font)
        baseline = (self.height() + metrics.ascent() - metrics.descent()) / 2.0
        view = QRectF(PAD_X, 1, max(0.0, self.width() - PAD_X - PAD_R), max(1.0, self.height() - 2))
        painter.save()
        painter.setClipRect(view)
        for word in self._words:
            if word.width <= 0.3 and word.out_opacity <= 0.02:
                continue
            x = PAD_X + word.x - self._scroll
            if x > view.right() + 4 or x + word.width < view.left() - 8:
                continue
            clip = QRectF(x, 0.0, max(word.width, 0.0), float(self.height()))
            painter.save()
            painter.setClipRect(clip, Qt.ClipOperation.IntersectClip)
            if word.outgoing and word.out_opacity > 0.02:
                painter.setOpacity(max(0.0, min(1.0, word.out_opacity)))
                painter.setPen(INK)
                painter.drawText(QPointF(x, baseline + word.y), word.outgoing)
            if word.text and word.opacity > 0.02:
                painter.setOpacity(max(0.0, min(1.0, word.opacity)))
                painter.setPen(INK)
                painter.drawText(QPointF(x, baseline + word.y), word.text)
            painter.restore()
        painter.restore()
        if self._scroll > 1.5:
            fade = QLinearGradient(PAD_X, 0, PAD_X + 26, 0)
            fade.setColorAt(0.0, BG)
            fade.setColorAt(1.0, QColor(BG.red(), BG.green(), BG.blue(), 0))
            painter.fillRect(QRectF(PAD_X, 1, 26, max(1, self.height() - 2)), fade)

    def paintEvent(self, _event):
        if not self._state:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        caption = self._state == "recording" and bool(self._words or self._line)
        if caption or self._message:
            rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
            path = QPainterPath()
            path.addRoundedRect(rect, 9, 9)
            painter.fillPath(path, BG)
            border = QColor(60, 66, 80) if self._state == "recording" else ERR
            painter.setPen(QPen(border, 1))
            painter.drawPath(path)
        self._draw(painter)
        if caption:
            self._paint_line(painter)
        elif self._message:
            painter.setPen(ERR)
            painter.setFont(QFont(self.font()))
            painter.drawText(
                QRectF(22, 0, self.width() - 26, self.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                self._message,
            )

    def _draw(self, painter):
        cx = 14.0 if (self._message or self._words) else self.width() / 2
        cy = self.height() / 2
        if self._state == "recording":
            pulse = 0.72 + 0.28 * (0.5 + 0.5 * math.sin(self._phase * 1.6))
            glow = QColor(REC)
            glow.setAlphaF(0.2 * pulse)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(cx, cy), 8 * pulse, 8 * pulse)
            painter.setBrush(REC)
            painter.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
            return
        if self._state == "busy":
            pen = QPen(BUSY, 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(QRectF(cx - 5, cy - 5, 10, 10), int(-self._phase * 320) % (360 * 16), 100 * 16)
            return
        if self._state == "done":
            pen = QPen(OK, 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(
                QPointF(cx - 3, cy + 0.2), QPointF(cx - 0.7, cy + 2.2), QPointF(cx + 3.2, cy - 2.4)
            )
            return
        pen = QPen(ERR, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(cx - 4, cy - 4), QPointF(cx + 4, cy + 4))
        painter.drawLine(QPointF(cx + 4, cy - 4), QPointF(cx - 4, cy + 4))
