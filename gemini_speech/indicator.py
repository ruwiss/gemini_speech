import math

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QFontMetrics
from PyQt6.QtWidgets import QWidget, QApplication

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
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(ICON, ICON)
        self._state = ""
        self._message = ""
        self._phase = 0.0
        self._area = None
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self.dismiss)

    def show_recording(self):
        self._show("recording", "", ICON, ICON)

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

    def _show(self, state, message, width, height, msec=0):
        self._state = state
        self._message = message
        self.resize(width, height)
        self._place()
        if not self.isVisible():
            self.show()
        if not self._timer.isActive():
            self._timer.start()
        self._hide.stop()
        if msec:
            self._hide.start(msec)
        self.update()

    def _place(self):
        pos = QCursor.pos()
        x = pos.x() + GAP
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

    def _tick(self):
        self._phase += 0.18
        before = self.pos()
        self._place()
        if self.pos() != before or self._state in ("recording", "busy"):
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
            painter.setPen(QPen(ERR, 1))
            painter.drawPath(path)
        self._draw(painter)
        if self._message:
            painter.setPen(ERR)
            painter.setFont(QFont(self.font()))
            painter.drawText(
                QRectF(22, 0, self.width() - 26, self.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
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
