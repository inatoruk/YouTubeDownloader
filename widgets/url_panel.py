"""URL入力パネルと一括入力ダイアログ。"""

from __future__ import annotations

import re
from urllib.parse import unquote

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QTextEdit, QDialog,
)
from PySide6.QtCore import Qt, Signal, QThread

from theme import Theme


# =============================================================================
# チャンネルURL取得ワーカー
# =============================================================================

class _ChannelFetchWorker(QThread):
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
            urls = downloader.extract_channel_urls(self.channel_url)
            self.urls_fetched.emit(urls)
        except Exception as exc:
            self.fetch_failed.emit(str(exc))


# =============================================================================
# カスタムウィジェット
# =============================================================================

class FocusPlaceholderLineEdit(QLineEdit):
    """フォーカス時にプレースホルダーを非表示にする入力欄。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_placeholder = ""
        self.textChanged.connect(self._auto_decode)

    def _auto_decode(self, text: str):
        if "%" in text:
            decoded = unquote(text)
            if decoded != text:
                self.setText(decoded)

    def focusInEvent(self, event):
        self._original_placeholder = self.placeholderText()
        self.setPlaceholderText("")
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        if not self.text():
            self.setPlaceholderText(self._original_placeholder)
        super().focusOutEvent(event)


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
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;")
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
                font-size: 13px;
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
            f"color: {Theme.TEXT_TERTIARY}; font-size: 12px;"
        )
        self.text_edit.textChanged.connect(self._auto_decode)
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

    def _auto_decode(self):
        text = self.text_edit.toPlainText()
        if "%" in text:
            decoded = unquote(text)
            if decoded != text:
                cursor = self.text_edit.textCursor()
                pos = cursor.position()
                diff = len(text) - len(decoded)
                new_pos = max(0, pos - diff)
                
                self.text_edit.blockSignals(True)
                self.text_edit.setPlainText(decoded)
                
                new_cursor = self.text_edit.textCursor()
                new_cursor.setPosition(new_pos)
                self.text_edit.setTextCursor(new_cursor)
                self.text_edit.blockSignals(False)

    def get_urls(self) -> list[str]:
        """入力されたURLリストを返す（空行除去済み）。"""
        text = self.text_edit.toPlainText()
        lines = text.replace(",", "\n").split("\n")
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

    # モバイル (m.) や YouTube Music (music.) のサブドメインも受け付ける。
    # iPhoneの共有メニューから貼り付けたURLは m.youtube.com になるため。
    _SUBDOMAIN = r'(www\.|m\.|music\.)?'
    _YOUTUBE_PATTERN = re.compile(
        rf'^(https?://)?{_SUBDOMAIN}(youtube\.com|youtu\.be)/.+'
    )
    _CHANNEL_PATTERN = re.compile(
        rf'^(https?://)?{_SUBDOMAIN}youtube\.com/'
        r'(@[\w.-]+|channel/[\w-]+|c/[\w.-]+|user/[\w.-]+)(/.*)?$'
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._channel_worker: _ChannelFetchWorker | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("URLを入力")
        title.setObjectName("Title")
        layout.addWidget(title)

        # URL入力行
        url_row = QHBoxLayout()
        self.url_input = FocusPlaceholderLineEdit()
        self.url_input.setPlaceholderText("ここにYouTubeのURLを貼り付け (⏎で追加)")
        self.url_input.returnPressed.connect(self._on_submit)
        url_row.addWidget(self.url_input)

        add_btn = QPushButton("追加")
        add_btn.setObjectName("secondary")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_submit)
        url_row.addWidget(add_btn)

        layout.addLayout(url_row)

        # ボタン行（一括追加 + チャンネル取得）
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        bulk_btn = QPushButton("URLを一括追加")
        bulk_btn.setObjectName("secondary")
        bulk_btn.setCursor(Qt.PointingHandCursor)
        bulk_btn.clicked.connect(self._on_bulk_add)
        btn_row.addWidget(bulk_btn)

        self.channel_btn = QPushButton("チャンネルから取得")
        self.channel_btn.setObjectName("secondary")
        self.channel_btn.setCursor(Qt.PointingHandCursor)
        self.channel_btn.clicked.connect(self._on_fetch_channel)
        btn_row.addWidget(self.channel_btn)

        layout.addLayout(btn_row)

    # =========================================================================
    # イベントハンドラ
    # =========================================================================

    def _on_submit(self):
        """単一URLを送信する。"""
        url = self.url_input.text().strip()
        if not url:
            return
        if not self._is_playlist_url(url) and not self._validate_youtube_url(url):
            self.status_message.emit(
                "無効なURLです。YouTubeのURLを入力してください。", True
            )
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

        # バリデーション: 無効な動画URLを除外
        valid = []
        invalid_count = 0
        for u in urls:
            if self._is_playlist_url(u) or self._validate_youtube_url(u):
                valid.append(u)
            else:
                invalid_count += 1

        if valid:
            self.bulk_urls_submitted.emit(valid)

        if invalid_count > 0:
            self.status_message.emit(
                f"{invalid_count} 件の無効なURLをスキップしました", True
            )

    def _on_fetch_channel(self):
        """チャンネルURLから全動画URLを取得する。

        入力欄にチャンネルURLが入力されていればそれを使用し、
        入力欄が空の場合はプレースホルダーのガイドを表示する。
        """
        # 既に取得中なら無視
        if self._channel_worker and self._channel_worker.isRunning():
            return

        url = self.url_input.text().strip()

        if not url:
            self.status_message.emit(
                "チャンネルURLを入力欄に入力してから「チャンネルから取得」を押してください。", True
            )
            return

        if not self._is_channel_url(url):
            self.status_message.emit(
                "チャンネルURLを入力してください（例: https://www.youtube.com/@channelname）", True
            )
            return

        # ローディング状態
        self.channel_btn.setEnabled(False)
        self.channel_btn.setText("取得中...")
        self.status_message.emit(f"チャンネルの動画URLを取得中: {url}", False)

        # バックグラウンドワーカー起動
        self._channel_worker = _ChannelFetchWorker(url, self)
        self._channel_worker.urls_fetched.connect(self._on_channel_urls_fetched)
        self._channel_worker.fetch_failed.connect(self._on_channel_fetch_failed)
        self._channel_worker.finished.connect(self._on_channel_worker_finished)
        self._channel_worker.start()

    def _on_channel_urls_fetched(self, urls: list[str]):
        """チャンネルURL取得成功時の処理。"""
        if not urls:
            self.status_message.emit("動画URLが見つかりませんでした。", True)
            return

        self.status_message.emit(f"{len(urls)} 件の動画URLを取得しました。", False)
        self.url_input.clear()

        # 一括入力ダイアログに取得結果を流し込む
        dialog = BulkUrlDialog(self, initial_urls=urls)
        if dialog.exec() != QDialog.Accepted:
            return

        confirmed_urls = dialog.get_urls()
        if confirmed_urls:
            self.bulk_urls_submitted.emit(confirmed_urls)

    def _on_channel_fetch_failed(self, error: str):
        """チャンネルURL取得失敗時の処理。"""
        self.status_message.emit(f"チャンネルの取得に失敗しました: {error}", True)

    def _on_channel_worker_finished(self):
        """ワーカー終了後のUI復元。"""
        self.channel_btn.setEnabled(True)
        self.channel_btn.setText("チャンネルから取得")
        if self._channel_worker:
            self._channel_worker.deleteLater()
            self._channel_worker = None

    # =========================================================================
    # 静的ヘルパー
    # =========================================================================

    @staticmethod
    def _validate_youtube_url(url: str) -> bool:
        """YouTube URLかどうかを検証する。"""
        return bool(UrlInputPanel._YOUTUBE_PATTERN.match(url))

    @staticmethod
    def _is_playlist_url(url: str) -> bool:
        """YouTube プレイリストURLかどうかを判定する。"""
        if re.search(r'youtube\.com/playlist\?', url):
            return True
        match = re.search(r'[?&]list=([^&]+)', url)
        if match:
            list_id = match.group(1)
            if not list_id.startswith(('RD', 'LL', 'FL', 'WL')):
                return True
        return False

    @staticmethod
    def _is_channel_url(url: str) -> bool:
        """YouTube チャンネルURLかどうかを判定する。"""
        return bool(UrlInputPanel._CHANNEL_PATTERN.match(url))
