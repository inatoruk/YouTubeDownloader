from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QLinearGradient
from PySide6.QtCore import Qt, QTimer

from theme import Theme

class SmoothProgressBar(QWidget):
    """
    macOSのネイティブQProgressBarの制限を回避し、
    完璧なカスタムデザインとイージング描画を行うための自作プログレスバー。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_progress = 0.0
        self._current_progress = 0.0
        self._radius = 3
        # デフォルトカラー
        self._color1 = QColor(Theme.ACCENT)
        self._color2 = QColor(Theme.ACCENT)
        
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._update_frame)
        # 非表示時などのリソース消費を抑えるため最初はタイマーを止めておく
        
    def setRadius(self, radius: int):
        self._radius = radius
        self.update()

    def setColors(self, color1: str, color2: str = None):
        """グラデーションまたは単色を設定する"""
        self._color1 = QColor(color1)
        self._color2 = QColor(color2 if color2 else color1)
        self.update()

    def setProgress(self, percent: float):
        """0.0 〜 1.0 の間で進捗をセットする"""
        self._target_progress = max(0.0, min(1.0, percent))
        if not self.anim_timer.isActive():
            self.anim_timer.start(16)  # 60fps
            
    def setProgressImmediate(self, percent: float):
        """アニメーションなしで即座に進捗をセットする"""
        self._target_progress = max(0.0, min(1.0, percent))
        self._current_progress = self._target_progress
        if self.anim_timer.isActive():
            self.anim_timer.stop()
        self.update()

    def reset(self):
        self._target_progress = 0.0
        self._current_progress = 0.0
        self.anim_timer.stop()
        self.update()

    def _update_frame(self):
        diff = self._target_progress - self._current_progress
        
        # 値が逆行した場合（映像から音声DLに切り替わり0に戻った時など）はバックせず即スナップする
        if diff < -0.05:
            self._current_progress = self._target_progress
            self.update()
        elif abs(diff) > 0.001:
            # 前進時のみ0.04倍ずつ目標に近づくイージングを適用
            self._current_progress += diff * 0.04
            self.update()
        else:
            self._current_progress = self._target_progress
            self.update()
            self.anim_timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 背景（トラック）
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(Theme.TRACK))
        painter.drawRoundedRect(self.rect(), self._radius, self._radius)
        
        # 進捗（チャンク）
        if self._current_progress > 0:
            prog_rect = self.rect()
            prog_rect.setWidth(int(self.width() * self._current_progress))
            if prog_rect.width() > 0:
                # 常にバー全体の幅に対するグラデーションにする（伸びるたびに変わるのを防ぐ場合）
                # 今回はCSSと同じく横幅全体固定のグラデーションにする
                grad = QLinearGradient(0, 0, self.width(), 0)
                grad.setColorAt(0, self._color1)
                grad.setColorAt(1, self._color2)
                painter.setBrush(grad)
                painter.drawRoundedRect(prog_rect, self._radius, self._radius)
