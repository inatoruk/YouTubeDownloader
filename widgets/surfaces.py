"""Device-pixel-aware background and compact native controls."""
from functools import lru_cache
import math
import random
from PySide6.QtCore import Qt, QPointF, QRectF, QSize, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QComboBox, QPushButton, QStyle, QStyleOptionButton, QStylePainter, QProxyStyle, QApplication, QSizePolicy, QStyledItemDelegate, QStyleOptionViewItem
from theme import Theme


@lru_cache(maxsize=4)
def gradient_image(width, height, top, bottom, dpr):
    """Stochastic rounding removes 8-bit bands with less than one level of noise.

    Noise is correlated across RGB, preventing colored speckles. The image is
    generated at device resolution and cached, never layered over text/controls.
    Byte translations keep the per-pixel work in C rather than Python loops.
    """
    start, end = QColor(top).getRgb()[:3], QColor(bottom).getRgb()[:3]
    rng = random.Random(617)
    data = bytearray(width * height * 4)
    for y in range(height):
        t = y / max(1, height - 1)
        t = t * t * (3 - 2 * t)
        noise = rng.randbytes(width)
        row = bytearray(width * 4)
        for channel in range(3):
            value = start[channel] + (end[channel] - start[channel]) * t
            base = math.floor(value)
            threshold = round((value-base)*256)
            table = bytes(base + (n < threshold) for n in range(256))
            row[channel::4] = noise.translate(table)
        row[3::4] = b'\xff' * width
        data[y*width*4:(y+1)*width*4] = row
    image = QImage(data, width, height, width*4, QImage.Format_RGBA8888).copy()
    image.setDevicePixelRatio(dpr)
    return image


class SidebarSurface(QFrame):
    def paintEvent(self, event):
        dpr = self.devicePixelRatioF()
        painter = QPainter(self)
        image = gradient_image(max(1, round(self.width()*dpr)), max(1, round(self.height()*dpr)),
                               Theme.SIDEBAR_TOP, Theme.SIDEBAR_BOTTOM, dpr)
        painter.drawImage(QPointF(0, 0), image)
        painter.setPen(QPen(QColor(Theme.CARD_BORDER), 1/dpr))
        painter.drawLine(QPointF(self.width()-0.5/dpr, 0), QPointF(self.width()-0.5/dpr, self.height()))


class ComboOptionDelegate(QStyledItemDelegate):
    """Explicit item insets, independent of the platform combo menu delegate."""
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        selected = bool(opt.state & QStyle.State_Selected)
        painter.save()
        painter.fillRect(opt.rect, QColor(Theme.ACCENT if selected else Theme.BG_CARD))
        painter.setPen(QColor(Theme.ON_ACCENT if selected else Theme.TEXT_PRIMARY))
        font = opt.font
        font.setPixelSize(17)
        painter.setFont(font)
        rect = opt.rect.adjusted(16, 7, -12, -7)
        text = painter.fontMetrics().elidedText(opt.text, Qt.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        font = opt.font
        font.setPixelSize(17)
        from PySide6.QtGui import QFontMetrics
        metrics = QFontMetrics(font)
        return QSize(metrics.horizontalAdvance(opt.text) + 28, max(48, metrics.height() + 14))


class AirComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(ComboOptionDelegate(self))

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(Theme.TEXT_SECONDARY), 1.25, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        x, y = self.width()-16, self.height()/2-1
        painter.drawLine(QPointF(x-3, y), QPointF(x, y+3))
        painter.drawLine(QPointF(x, y+3), QPointF(x+3, y))


class SegmentButton(QPushButton):
    """Draw the segment label without the native focus rectangle."""
    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.state &= ~QStyle.State_HasFocus
        painter = QStylePainter(self)
        painter.drawControl(QStyle.CE_PushButton, option)


class SolidFocusStyle(QProxyStyle):
    """Suppress native focus frames while retaining keyboard navigation."""
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_FrameFocusRect:
            return
        super().drawPrimitive(element, option, painter, widget)


def install_focus_style():
    app = QApplication.instance()
    if app is not None and not hasattr(app, '_air_focus_style'):
        # QProxyStyle without a supplied base preserves the platform's native style.
        style = SolidFocusStyle()
        app.setStyle(style)
        app._air_focus_style = style


class AnimatedSegment(QFrame):
    """An interruptible selection whose leading edge pulls the tail along."""
    def __init__(self, parent=None):
        super().__init__(parent)
        # Quality controls change height between modes; the selector must not
        # absorb that space and move its buttons during the slide.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._buttons = []
        self._selection = QRectF()
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(240)
        self._animation.setEasingCurve(QEasingCurve.Linear)
        self._animation.valueChanged.connect(self._animate_edges)
        self._animation.finished.connect(lambda: self._step(self._target()))

    def bind(self, buttons):
        self._buttons = list(buttons)
        for button in self._buttons:
            button.toggled.connect(lambda checked: self._move_selection() if checked else None)

    def _step(self, rect):
        self._selection = rect
        self.update()

    def _target(self):
        button = next((b for b in self._buttons if b.isChecked()), None)
        return QRectF(button.geometry()) if button else QRectF()

    def _animate_edges(self, phase):
        start, end = self._start_rect, self._end_rect
        lead = 1 - (1 - phase) ** 3
        tail_time = max(0.0, (phase - 80 / 240) / (1 - 80 / 240))
        tail = tail_time * tail_time * (3 - 2 * tail_time)
        rightward = end.center().x() >= start.center().x()
        left_progress, right_progress = (tail, lead) if rightward else (lead, tail)
        left = start.left() + (end.left() - start.left()) * left_progress
        right = start.right() + (end.right() - start.right()) * right_progress
        bounds = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        left = max(bounds.left(), min(left, bounds.right()))
        right = max(left, min(right, bounds.right()))
        self._step(QRectF(left, end.top(), right - left, end.height()))

    def _move_selection(self):
        target = self._target()
        self._animation.stop()
        if self._selection.isEmpty() or not self.isVisible() or not self.style().styleHint(QStyle.SH_Widget_Animate, None, self):
            self._step(target)
            return
        self._start_rect = QRectF(self._selection)
        self._end_rect = target
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.layout():
            self.layout().activate()
        self._animation.stop()
        self._step(self._target())

    def showEvent(self, event):
        super().showEvent(event)
        self._step(self._target())

    def hideEvent(self, event):
        self._animation.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(Theme.TRACK))
        painter.drawRoundedRect(QRectF(self.rect()), 10, 10)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 8, 8)
        painter.setClipPath(clip)
        rect = self._selection if not self._selection.isEmpty() else self._target()
        painter.setBrush(QColor(0, 0, 0, 12))
        painter.drawRoundedRect(rect.translated(0, 1), 7, 7)
        painter.setBrush(QColor(Theme.BG_CARD))
        painter.drawRoundedRect(rect, 7, 7)
