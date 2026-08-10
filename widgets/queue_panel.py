"""ダウンロードキュー表示パネル。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea,
    QSizePolicy
)
from PySide6.QtCore import Qt, Signal

from theme import Theme, STATUS_ICONS
from queue_manager import DownloadItem, ItemStatus
from widgets.smooth_progress import SmoothProgressBar


class QueueItemWidget(QFrame):
    """キュー内の1アイテムを表示するカスタムウィジェット。"""

    remove_clicked = Signal(str)
    retry_clicked = Signal(str)

    def __init__(self, item_id: str, item: DownloadItem, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        
        self.setObjectName("QueueItem")
        self.setStyleSheet(f"""
            QFrame#QueueItem {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.CARD_BORDER};
                border-radius: 12px;
            }}
        """)
        self._build_ui(item)

    def _build_ui(self, item: DownloadItem):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # ステータスアイコン
        self.status_icon = QLabel(STATUS_ICONS.get(item.status, "⏳"))
        self.status_icon.setFixedWidth(28)
        self.status_icon.setAlignment(Qt.AlignCenter)
        self.status_icon.setStyleSheet("font-size: 16px;")
        layout.addWidget(self.status_icon)

        # タイトル＋URL 列
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self.title_label = QLabel(item.title or self._shorten_url(item.url))
        self.title_label.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 500;
            color: {Theme.TEXT_PRIMARY};
        """)
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label)

        self.url_label = QLabel(self._shorten_url(item.url))
        self.url_label.setStyleSheet(f"""
            font-size: 11px;
            color: {Theme.TEXT_TERTIARY};
        """)
        info_layout.addWidget(self.url_label)

        self.progress_bar = SmoothProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRadius(3)
        self.progress_bar.setProgressImmediate(item.progress / 100.0)
        info_layout.addWidget(self.progress_bar)

        layout.addLayout(info_layout, 1)

        # メタ情報（時間・サイズ）
        meta_layout = QVBoxLayout()
        meta_layout.setSpacing(2)
        meta_layout.setAlignment(Qt.AlignCenter)

        self.duration_label = QLabel(item.duration or "")
        self.duration_label.setStyleSheet(f"font-size: 11px; color: {Theme.TEXT_TERTIARY};")
        self.duration_label.setAlignment(Qt.AlignCenter)
        
        self.size_label = QLabel(item.filesize or "")
        self.size_label.setStyleSheet(f"font-size: 10px; color: {Theme.TEXT_TERTIARY};")
        self.size_label.setAlignment(Qt.AlignCenter)
        
        meta_layout.addWidget(self.duration_label)
        meta_layout.addWidget(self.size_label)
        
        meta_widget = QWidget()
        meta_widget.setLayout(meta_layout)
        meta_widget.setFixedWidth(70)
        layout.addWidget(meta_widget)

        # 操作ボタン
        self.retry_btn = QPushButton("↻")
        self.retry_btn.setFixedSize(28, 28)
        self.retry_btn.setToolTip("リトライ")
        self.retry_btn.setCursor(Qt.PointingHandCursor)
        self.retry_btn.setVisible(False)
        self.retry_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.INPUT_BG};
                border: 1px solid {Theme.INPUT_BORDER};
                border-radius: 14px;
                color: {Theme.WARNING};
                font-size: 14px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {Theme.CARD_BORDER};
            }}
        """)
        self.retry_btn.clicked.connect(
            lambda: self.retry_clicked.emit(self.item_id)
        )
        layout.addWidget(self.retry_btn)

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setFixedSize(28, 28)
        self.remove_btn.setToolTip("削除")
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.INPUT_BG};
                border: 1px solid {Theme.INPUT_BORDER};
                border-radius: 14px;
                color: {Theme.ERROR};
                font-size: 12px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {Theme.CARD_BORDER};
            }}
        """)
        self.remove_btn.clicked.connect(
            lambda: self.remove_clicked.emit(self.item_id)
        )
        layout.addWidget(self.remove_btn)

    @staticmethod
    def _shorten_url(url: str) -> str:
        """表示用にURLを短縮する。"""
        if len(url) > 60:
            return url[:57] + "..."
        return url

    def update_status(self, status: ItemStatus):
        self.status_icon.setText(STATUS_ICONS.get(status, "⋯"))
        
        icon_color = {
            ItemStatus.COMPLETED: Theme.SUCCESS,
            ItemStatus.FAILED: Theme.ERROR,
            ItemStatus.CANCELLED: Theme.TEXT_TERTIARY,
            ItemStatus.DOWNLOADING: Theme.ACCENT,
            ItemStatus.RESOLVING: Theme.ACCENT_LIGHT,
        }.get(status, Theme.TEXT_SECONDARY)

        self.status_icon.setStyleSheet(f"font-size: 16px; font-weight: 800; color: {icon_color}; background: transparent;")

        self.retry_btn.setVisible(
            status in (ItemStatus.FAILED, ItemStatus.CANCELLED)
        )
        if status == ItemStatus.COMPLETED:
            self.progress_bar.setProgressImmediate(1.0)
            self.progress_bar.setColors(Theme.SUCCESS)
        elif status == ItemStatus.FAILED:
            self.progress_bar.setColors(Theme.ERROR)

    def update_progress(self, percent: float):
        # percentは0〜100で渡されるので0.0〜1.0に正規化する
        self.progress_bar.setProgress(percent / 100.0)

    def update_title(self, title: str):
        self.title_label.setText(title)

    def update_duration(self, duration: str):
        self.duration_label.setText(duration)

    def update_filesize(self, filesize: str):
        self.size_label.setText(filesize)


class QueuePanel(QFrame):
    """ダウンロードキュー表示・操作パネル。

    Signals:
        remove_item(str): アイテム削除リクエスト (item_id)
        retry_item(str): アイテムリトライリクエスト (item_id)
        retry_all_failed(): 全失敗アイテムリトライ
        clear_completed(): 完了済みクリア
    """

    remove_item = Signal(str)
    retry_item = Signal(str)
    retry_all_failed = Signal()
    clear_completed = Signal()
    clear_all = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._widgets: dict[str, QueueItemWidget] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("ダウンロードキュー")
        title.setObjectName("Title")
        layout.addWidget(title)

        # キュー件数
        self.count_label = QLabel("0 件")
        self.count_label.setStyleSheet(f"""
            font-size: 12px;
            color: {Theme.TEXT_TERTIARY};
        """)
        layout.addWidget(self.count_label)

        # スクロールエリア
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        # 高さは_adjust_heightで動的に計算する
        self.scroll.setMinimumHeight(80)
        self.scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setSpacing(6)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.addStretch()

        self.scroll.setWidget(self.list_widget)
        layout.addWidget(self.scroll)

        # 空メッセージ
        self.empty_label = QLabel("URLを追加してください")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"""
            color: {Theme.TEXT_TERTIARY};
            font-size: 13px;
            padding: 20px;
        """)
        layout.addWidget(self.empty_label)

        # 操作ボタン
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.retry_all_btn = QPushButton("失敗を再試行")
        self.retry_all_btn.setObjectName("secondary")
        self.retry_all_btn.setCursor(Qt.PointingHandCursor)
        self.retry_all_btn.clicked.connect(self.retry_all_failed.emit)
        self.retry_all_btn.setVisible(False)
        btn_row.addWidget(self.retry_all_btn)

        self.clear_btn = QPushButton("完了をクリア")
        self.clear_btn.setObjectName("secondary")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_completed.emit)
        self.clear_btn.setVisible(False)
        btn_row.addWidget(self.clear_btn)

        self.clear_all_btn = QPushButton("すべてクリア")
        self.clear_all_btn.setObjectName("secondary")
        self.clear_all_btn.setCursor(Qt.PointingHandCursor)
        self.clear_all_btn.setStyleSheet(f"color: {Theme.ERROR};")
        self.clear_all_btn.clicked.connect(self.clear_all.emit)
        self.clear_all_btn.setVisible(False)
        btn_row.addWidget(self.clear_all_btn)

        layout.addLayout(btn_row)

    # --- 内部メソッド ---

    def _adjust_height(self):
        """アイテム数に応じてスクロールエリアの高さを動的に調整する（最大600px）。"""
        count = len(self._widgets)
        if count == 0:
            return
        # 1アイテムあたりおよそ 74px + 上下マージン
        target_height = min(count * 74 + 12, 600)
        self.scroll.setMinimumHeight(target_height)
        self.scroll.setMaximumHeight(target_height)

    # --- 公開API ---

    def add_item(self, item_id: str, item: DownloadItem):
        """キューにアイテムウィジェットを追加する。"""
        widget = QueueItemWidget(item_id, item)
        widget.remove_clicked.connect(self.remove_item.emit)
        widget.retry_clicked.connect(self.retry_item.emit)
        self._widgets[item_id] = widget
        self.list_layout.insertWidget(
            self.list_layout.count() - 1, widget
        )
        self._adjust_height()

    def remove_widget(self, item_id: str):
        """ウィジェットを完全削除する。"""
        widget = self._widgets.pop(item_id, None)
        if widget:
            widget.setParent(None)
            widget.deleteLater()
            self._adjust_height()

    def update_item_progress(self, item_id: str, percent: float):
        widget = self._widgets.get(item_id)
        if widget:
            widget.update_progress(percent)

    def update_item_status(self, item_id: str, status: ItemStatus):
        widget = self._widgets.get(item_id)
        if widget:
            widget.update_status(status)

    def update_item_title(self, item_id: str, title: str):
        widget = self._widgets.get(item_id)
        if widget:
            widget.update_title(title)

    def update_item_duration(self, item_id: str, duration: str):
        if item_id in self._widgets:
            self._widgets[item_id].update_duration(duration)

    def update_item_filesize(self, item_id: str, filesize: str):
        if item_id in self._widgets:
            self._widgets[item_id].update_filesize(filesize)

    def rebuild(self, items: list[DownloadItem]):
        """全ウィジェットを再構築する。"""
        for widget in self._widgets.values():
            widget.setParent(None)
            widget.deleteLater()
        self._widgets.clear()

        for item in items:
            self.add_item(item.id, item)
            widget = self._widgets[item.id]
            widget.update_status(item.status)
            widget.update_progress(item.progress)
            if item.title:
                widget.update_title(item.title)
            if item.duration:
                widget.update_duration(item.duration)
        self._adjust_height()

    def update_counts(
        self,
        total: int,
        completed: int,
        failed: int,
        is_running: bool,
    ):
        """件数表示・ボタンの表示状態を更新する。"""
        visible = len(self._widgets)
        self.empty_label.setVisible(visible == 0)
        self.scroll.setVisible(visible > 0)

        if total == 0:
            self.count_label.setText("0 件")
        else:
            parts = [f"全 {total} 件"]
            if completed:
                parts.append(f"完了 {completed}")
            if failed:
                parts.append(f"失敗 {failed}")
            self.count_label.setText(" / ".join(parts))

        self.retry_all_btn.setVisible(failed > 0 and not is_running)
        self.clear_btn.setVisible(
            (completed > 0 or failed > 0) and not is_running
        )
        self.clear_all_btn.setVisible(total > 0 and not is_running)
