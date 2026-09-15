"""URL入力パネルと一括入力ダイアログ。"""

from __future__ import annotations


from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QTextEdit, QDialog,
)
from PySide6.QtCore import Qt, Signal, Slot

from theme import Theme
from utils.urls import classify_url
from utils.worker import CancellableWorker


# =============================================================================
# チャンネルURL取得ワーカー
# =============================================================================

class _ChannelFetchWorker(CancellableWorker):
    """チャンネルURLから全動画URLをバックグラウンドで取得するワーカー。"""

    urls_fetched = Signal(list)    # (urls: list[str])
    fetch_failed = Signal(str)     # (error_message: str)

    def __init__(self, channel_url: str, parent=None):
        super().__init__(parent)
        self.channel_url = channel_url

    def run(self):
        try:
            from downloader import Downloader
            downloader = Downloader(auto_update=False)
            urls = downloader.extract_channel_urls(self.channel_url, self.is_cancelled)
            self.urls_fetched.emit(urls)
        except Exception as exc:
            self.fetch_failed.emit(str(exc))


# =============================================================================
# カスタムウィジェット
# =============================================================================

class FocusPlaceholderLineEdit(QLineEdit):
    """Native input behavior: keep the prompt visible until text is entered."""


# =============================================================================
# 一括入力ダイアログ
# =============================================================================

class BulkUrlDialog(QDialog):
    """複数URLを一括入力するダイアログ。"""

    def __init__(self, parent=None, initial_urls: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("URLを一括追加")
        self.setMinimumSize(520, 380)
        self._build_ui()
        if initial_urls:
            self.text_edit.setPlainText("\n".join(initial_urls))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 説明
        desc = QLabel(
            "YouTube の URL を1行に1つずつ入力してください。\n"
            "プレイリストURLを指定すると、中の動画を自動展開します。"
        )
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 16px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # テキストエリア
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "https://www.youtube.com/watch?v=xxxxx\n"
            "https://www.youtube.com/watch?v=yyyyy\n"
            "https://www.youtube.com/playlist?list=zzzzz"
        )
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Theme.INPUT_BG};
                border: 1px solid {Theme.INPUT_BORDER};
                border-radius: 10px;
                padding: 12px;
                color: {Theme.TEXT_PRIMARY};
                font-size: 16px;
                font-family: "SF Mono", "Menlo", monospace;
            }}
            QTextEdit:focus {{
                border: 2px solid {Theme.ACCENT};
            }}
        """)
        layout.addWidget(self.text_edit)

        # URL数表示
        self.count_label = QLabel("0 件のURL")
        self.count_label.setStyleSheet(
            f"color: {Theme.TEXT_TERTIARY}; font-size: 15px;"
        )

        self.text_edit.textChanged.connect(self._update_count)
        layout.addWidget(self.count_label)

        # ボタン
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("キャンセル")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setCursor(Qt.PointingHandCursor)

        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self.accept)
        add_btn.setCursor(Qt.PointingHandCursor)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(add_btn)
        layout.addLayout(btn_layout)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {Theme.BG_DARK};
            }}
        """)

    def _update_count(self):
        urls = self.get_urls()
        self.count_label.setText(f"{len(urls)} 件のURL")

    def get_urls(self) -> list[str]:
        """入力されたURLリストを返す（空行除去済み）。"""
        text = self.text_edit.toPlainText()
        lines = text.splitlines()
        return [line.strip() for line in lines if line.strip()]


# =============================================================================
# URL入力パネル
# =============================================================================

class UrlInputPanel(QFrame):
    """URL入力カード。

    Signals:
        url_submitted(str): 単一URLが送信された時
        bulk_urls_submitted(list[str]): 一括URLが送信された時
        status_message(str, bool): ステータスメッセージ (msg, is_error)
    """

    url_submitted = Signal(str)
    bulk_urls_submitted = Signal(list)
    status_message = Signal(str, bool)
    channel_confirmed = Signal(list, bool)
    state_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._channel_worker: _ChannelFetchWorker | None = None
        self._channel_queue = []
        self._generation = 0
        self._closing = False
        self._channel_dialog = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)


        # URL入力行
        url_row = QHBoxLayout()
        url_row.setContentsMargins(0, 0, 0, 0)
        url_row.setSpacing(10)
        self.url_input = FocusPlaceholderLineEdit()
        self.url_input.setPlaceholderText("動画・プレイリストのURLを入力")
        self.url_input.returnPressed.connect(self._on_submit)
        url_row.addWidget(self.url_input)

        add_btn = QPushButton("追加")
        add_btn.setObjectName("secondary")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_add_clicked)
        add_btn.setToolTip("入力欄が空の場合、クリップボードから追加")
        self.add_btn = add_btn
        url_row.addWidget(add_btn)

        layout.addLayout(url_row)

        # ボタン行（一括追加 + チャンネル取得）
        btn_row = QHBoxLayout()


        bulk_btn = QPushButton("URLを一括追加")
        bulk_btn.setObjectName("link")
        bulk_btn.setCursor(Qt.PointingHandCursor)
        bulk_btn.clicked.connect(self._on_bulk_add)
        btn_row.addWidget(bulk_btn)

        self.channel_btn = QPushButton("チャンネルから取得")
        self.channel_btn.setObjectName("link")
        self.channel_btn.setCursor(Qt.PointingHandCursor)
        self.channel_btn.clicked.connect(self._on_fetch_channel)
        btn_row.addWidget(self.channel_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    # =========================================================================
    # イベントハンドラ
    # =========================================================================

    def _on_add_clicked(self):
        if self.url_input.text().strip():
            self._on_submit()
            return
        text = QApplication.clipboard().text().strip()
        if not text:
            self.status_message.emit("クリップボードにURLがありません", True)
            return
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) > 1:
            dialog = BulkUrlDialog(self, initial_urls=lines)
            if dialog.exec() == QDialog.Accepted and dialog.get_urls():
                self.bulk_urls_submitted.emit(dialog.get_urls())
            return
        self.url_input.setText(text)
        self._on_submit()

    def _on_submit(self):
        """単一URLを送信する。"""
        url = self.url_input.text().strip()
        if not url:
            self.status_message.emit("URLを入力してください", True)
            return
        try:
            url, _ = classify_url(url)
        except ValueError as exc:
            self.status_message.emit(str(exc), True)
            return
        self.url_submitted.emit(url)
        self.url_input.clear()

    def _on_bulk_add(self):
        """一括追加ダイアログを表示する。"""
        dialog = BulkUrlDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        urls = dialog.get_urls()
        if not urls:
            return

        self.bulk_urls_submitted.emit(urls)

    @property
    def busy(self):
        return self._channel_worker is not None

    def cancel_auto_start(self):
        if self._channel_worker:
            self._channel_worker.auto_start = False
        self._channel_queue = [(url, False) for url, _ in self._channel_queue]

    def invalidate(self):
        self._generation += 1
        self._channel_queue.clear()
        if self._channel_worker:
            self._channel_worker.cancel()
        if self._channel_dialog:
            self._channel_dialog.reject()

    def shutdown(self):
        self._closing = True
        self.invalidate()

    def _on_fetch_channel(self):
        self.request_channel(self.url_input.text(), False)

    def request_channel(self, url, auto_start=False):
        if self._closing:
            return
        try:
            url, kind = classify_url(url)
            if kind != 'channel':
                raise ValueError('チャンネルURLを入力してください')
        except ValueError as exc:
            self.status_message.emit(str(exc), True)
            return
        self._channel_queue.append((url, auto_start))
        self._pump_channels()

    def _pump_channels(self):
        if self._closing or self._channel_worker or self._channel_dialog or not self._channel_queue:
            return
        url, auto_start = self._channel_queue.pop(0)
        self.channel_btn.setEnabled(False)
        self.channel_btn.setText('取得中...')
        self.status_message.emit(f'チャンネルの動画URLを取得中: {url}', False)
        worker = _ChannelFetchWorker(url, self)
        worker.generation = self._generation
        worker.auto_start = auto_start
        self._channel_worker = worker
        worker.urls_fetched.connect(self._on_channel_urls_fetched)
        worker.fetch_failed.connect(self._on_channel_fetch_failed)
        worker.finished.connect(self._on_channel_worker_finished)
        worker.start()
        self.state_changed.emit()

    @Slot(list)
    def _on_channel_urls_fetched(self, urls):
        worker = self.sender()
        if self._closing or worker.generation != self._generation:
            return
        if not urls:
            self.status_message.emit('動画URLが見つかりませんでした。', True)
            return
        generation, auto_start = worker.generation, worker.auto_start
        self.url_input.clear()
        dialog = BulkUrlDialog(self, initial_urls=urls)
        self._channel_dialog = dialog
        accepted = dialog.exec() == QDialog.Accepted
        self._channel_dialog = None
        if accepted and not self._closing and generation == self._generation:
            self.channel_confirmed.emit(dialog.get_urls(), auto_start)
        dialog.deleteLater()
        self._pump_channels()

    @Slot(str)
    def _on_channel_fetch_failed(self, error):
        worker = self.sender()
        if not self._closing and worker.generation == self._generation:
            self.status_message.emit(f'チャンネルの取得に失敗しました: {error}', True)

    @Slot()
    def _on_channel_worker_finished(self):
        worker = self.sender()
        if self._channel_worker is worker:
            self._channel_worker = None
        worker.deleteLater()
        self.channel_btn.setEnabled(not self._closing)
        self.channel_btn.setText('チャンネルから取得')
        self._pump_channels()
        self.state_changed.emit()

    # =========================================================================
    # 静的ヘルパー
    # =========================================================================

    @staticmethod
    def _validate_youtube_url(url: str) -> bool:
        try:
            classify_url(url)
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_playlist_url(url: str) -> bool:
        try:
            return classify_url(url)[1] == 'playlist'
        except ValueError:
            return False

    @staticmethod
    def _is_channel_url(url: str) -> bool:
        try:
            return classify_url(url)[1] == 'channel'
        except ValueError:
            return False
