"""全体進捗表示パネル。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)
from PySide6.QtCore import Qt

from theme import Theme
from widgets.smooth_progress import SmoothProgressBar


class ProgressPanel(QFrame):
    """全体進捗バー・ステータスラベル・完了数を表示するカード。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("全体進捗")
        title.setObjectName("Title")
        layout.addWidget(title)

        self.progress_bar = SmoothProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setRadius(6)

        self.status_label = QLabel("待機中")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")

        self.percent_label = QLabel("0/0 完了")
        self.percent_label.setAlignment(Qt.AlignRight)

        info_row = QHBoxLayout()
        info_row.addWidget(self.status_label)
        info_row.addStretch()
        info_row.addWidget(self.percent_label)

        layout.addWidget(self.progress_bar)
        layout.addLayout(info_row)

    # --- 公開API ---

    def set_status(self, msg: str, is_error: bool = False):
        """ステータスメッセージを設定する。"""
        color = Theme.ERROR if is_error else Theme.TEXT_SECONDARY
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.status_label.setText(msg)

    def update_progress(self, percent: float, completed: int, total: int):
        """全体進捗を更新する。"""
        # percentは0〜100で渡されるので0.0〜1.0に正規化する
        normalized = percent / 100.0
        if completed == total and total > 0:
            self.progress_bar.setProgressImmediate(normalized)
        else:
            self.progress_bar.setProgress(normalized)
        self.percent_label.setText(f"{completed}/{total} 完了")

    def reset(self):
        """進捗をリセットする。"""
        self.progress_bar.reset()
        self.percent_label.setText("0/0 完了")


