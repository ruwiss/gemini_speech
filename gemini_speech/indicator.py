import math
import sys

from PyQt6.QtCore import Qt, QTimer, QRect, QRectF, QPointF
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QFontMetrics
from PyQt6.QtWidgets import QWidget, QApplication

from . import desktop

ICON = 28
GAP = 8
REC = QColor(240, 78, 82)
OK = QColor(80, 205, 140)
ERR = QColor(240, 100, 90)
BUSY = QColor(120, 170, 255)
BG = QColor(22, 24, 29, 230)


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
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self.dismiss)

    def show_recording(self, text=""):
        text = " ".join((text or "").split())
        if len(text) > 240:
            text = "…" + text[-239:]
        if text == self._message and self._state == "recording" and self.isVisible():
            return
        if not text:
            self._show("recording", "", ICON, ICON)
            return
        font = self._caption_font()
        metrics = QFontMetrics(font)
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)
        bounds = metrics.boundingRect(QRect(0, 0, 360, 160), flags, text)
        width = min(420, max(160, bounds.width() + 40))
        height = min(96, max(28, bounds.height() + 12))
        self._show("recording", text, width, height)

    def _caption_font(self):
        font = QFont(self.font())
        font.setPixelSize(13)
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
        self.hide()
        desktop.overlay_hidden()

    def _show(self, state, message, width, height, msec=0):
        self._state = state
        self._message = message
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
        self._phase += 0.36
        self._place()
        if self._state in ("recording", "busy"):
            self.update()

    def paintEvent(self, _event):
        if not self._state:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._message:
            rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
            path = QPainterPath()
            path.addRoundedRect(rect, 8, 8)
            painter.fillPath(path, BG)
            border = QColor(60, 66, 80) if self._state == "recording" else ERR
            painter.setPen(QPen(border, 1))
            painter.drawPath(path)
        self._draw(painter)
        if self._message:
            preview = self._state == "recording"
            painter.setPen(QColor(231, 233, 238) if preview else ERR)
            painter.setFont(self._caption_font() if preview else QFont(self.font()))
            flags = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            if preview:
                flags |= Qt.TextFlag.TextWordWrap
            painter.drawText(
                QRectF(28 if preview else 22, 0, self.width() - (34 if preview else 26), self.height()),
                int(flags),
                self._message,
            )

    def _draw(self, painter):
        cx = 14.0 if self._message else self.width() / 2
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
