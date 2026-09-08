"""YouTube Downloader メインウィンドウ。

各UIパネルを組み合わせ、BatchDownloadManager との橋渡しを行う。
ビジネスロジックやUI構築の詳細は各パネルモジュールに委譲している。
"""

from __future__ import annotations

import sys
import os
import logging
import re
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QScrollArea,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QEvent, QUrl, QTranslator, QLibraryInfo
from PySide6.QtGui import (
    QColor, QPalette, QKeySequence, QShortcut, QDesktopServices,
)

from downloader import (
    DownloadRequest, Downloader,
    is_yt_dlp_stale, yt_dlp_age_days, yt_dlp_version,
)
from queue_manager import BatchDownloadManager, DownloadItem, ItemStatus
from theme import Theme, build_global_stylesheet
from widgets import UrlInputPanel, QueuePanel, FormatPanel, ProgressPanel

logger = logging.getLogger(__name__)


# =============================================================================
# yt-dlp 更新ワーカー
# =============================================================================
class _YtDlpUpdateWorker(QThread):
    """起動時にバックグラウンドで yt-dlp の更新を確認するワーカー。"""

    def run(self):
        try:
            Downloader()._ensure_updated()
        except Exception as exc:
            logger.warning("バックグラウンド更新チェックに失敗しました: %s", exc)


# =============================================================================
# メインウィンドウ
# =============================================================================
class MainWindow(QMainWindow):
    """アプリケーションのメインウィンドウ。

    UIの構築は各パネルウィジェットに委譲し、
    ここではパネル同士とBatchDownloadManagerの接続（オーケストレーション）のみ行う。
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Downloader")
        self.resize(720, 750)

        # バッチマネージャー
        self._batch_manager = BatchDownloadManager(max_concurrent=2)

        self._apply_palette()
        self._build_ui()
        self._setup_shortcuts()
        self._connect_signals()

    # =========================================================================
    # 初期化
    # =========================================================================

    def _apply_palette(self):
        """ダークテーマのパレットとグローバルスタイルシートを適用する。"""
        p = self.palette()
        p.setColor(QPalette.Window, QColor(Theme.BG_DARK))
        p.setColor(QPalette.WindowText, QColor(Theme.TEXT_PRIMARY))
        p.setColor(QPalette.Base, QColor(Theme.BG_DARK))
        p.setColor(QPalette.AlternateBase, QColor(Theme.BG_CARD))
        p.setColor(QPalette.ToolTipBase, QColor(Theme.BG_CARD))
        p.setColor(QPalette.ToolTipText, QColor(Theme.TEXT_PRIMARY))
        p.setColor(QPalette.Text, QColor(Theme.TEXT_PRIMARY))
        p.setColor(QPalette.Button, QColor(Theme.BG_CARD))
        p.setColor(QPalette.ButtonText, QColor(Theme.TEXT_PRIMARY))
        p.setColor(QPalette.BrightText, QColor(Theme.ACCENT))
        p.setColor(QPalette.Link, QColor(Theme.ACCENT))
        p.setColor(QPalette.Highlight, QColor(Theme.ACCENT))
        p.setColor(QPalette.HighlightedText, QColor(Theme.TEXT_PRIMARY))
        self.setPalette(p)
        self.setStyleSheet(build_global_stylesheet())

    def _build_ui(self):
        """UIを構築する。各セクションはパネルウィジェットに委譲。"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setSpacing(20)
        layout.setContentsMargins(24, 24, 24, 24)

        # 1. ヘッダー
        self._build_header(layout)

        # 2. URL入力パネル
        self.url_panel = UrlInputPanel()
        layout.addWidget(self.url_panel)

        # 3. キューパネル
        self.queue_panel = QueuePanel()
        layout.addWidget(self.queue_panel)

        # 4. 形式パネル
        self.format_panel = FormatPanel()
        layout.addWidget(self.format_panel)

        # 5. 保存先
        self._build_output_card(layout)

        # 6. 進捗パネル
        self.progress_panel = ProgressPanel()
        layout.addWidget(self.progress_panel)

        # 7. 操作ボタン
        self._build_control_card(layout)

        layout.addStretch()
        main_layout.addWidget(scroll)

    def _build_header(self, parent_layout: QVBoxLayout):
        """ヘッダー部分を構築する。"""
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 16)
        header_layout.setSpacing(4)

        title = QLabel("YouTube Downloader")
        title.setStyleSheet(f"""
            font-size: 28px; font-weight: 700;
            color: {Theme.TEXT_PRIMARY}; background: transparent;
        """)

        subtitle = QLabel("動画・音声を高品質でダウンロード — 一括対応")
        subtitle.setStyleSheet(f"""
            font-size: 14px; font-weight: 400;
            color: {Theme.TEXT_SECONDARY}; background: transparent;
        """)

        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        parent_layout.addWidget(header)

    def _build_output_card(self, parent_layout: QVBoxLayout):
        """保存先カードを構築する。"""
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("保存先")
        title.setObjectName("Title")
        layout.addWidget(title)

        row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setText(str(os.path.expanduser("~/Downloads")))
        self.output_edit.setReadOnly(True)
        self.output_edit.setCursor(Qt.PointingHandCursor)
        self.output_edit.installEventFilter(self)

        change_btn = QPushButton("変更")
        change_btn.setObjectName("secondary")
        change_btn.setCursor(Qt.PointingHandCursor)
        change_btn.clicked.connect(self._on_browse)

        row.addWidget(self.output_edit)
        row.addWidget(change_btn)
        layout.addLayout(row)
        parent_layout.addWidget(card)

    def _build_control_card(self, parent_layout: QVBoxLayout):
        """操作ボタンカードを構築する。"""
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("操作")
        title.setObjectName("Title")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.addStretch()

        self.download_btn = QPushButton("ダウンロード開始")
        self.download_btn.setMinimumHeight(44)
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.clicked.connect(self._on_start_batch)

        self.stop_btn = QPushButton("全て停止")
        self.stop_btn.setObjectName("secondary")
        self.stop_btn.setMinimumHeight(44)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(self._on_stop_all)
        self.stop_btn.setVisible(False)

        close_btn = QPushButton("閉じる")
        close_btn.setObjectName("secondary")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.close)

        row.addWidget(self.download_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(close_btn)
        layout.addLayout(row)
        parent_layout.addWidget(card)

    def _setup_shortcuts(self):
        """キーボードショートカットを設定する。"""
        shortcut = QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Return), self)
        shortcut.activated.connect(
            lambda: self._on_start_batch() if self.download_btn.isEnabled() else None
        )

    # =========================================================================
    # シグナル接続
    # =========================================================================

    def _connect_signals(self):
        """全パネルとBatchDownloadManagerのシグナルを接続する。"""
        mgr = self._batch_manager

        # URL パネル → マネージャー
        self.url_panel.url_submitted.connect(self._on_url_submitted)
        self.url_panel.bulk_urls_submitted.connect(self._on_bulk_urls_submitted)
        self.url_panel.status_message.connect(
            lambda msg, err: self.progress_panel.set_status(msg, err)
        )

        # キューパネル → マネージャー
        self.queue_panel.remove_item.connect(self._on_remove_item)
        self.queue_panel.retry_item.connect(self._on_retry_item)
        self.queue_panel.retry_all_failed.connect(self._on_retry_all_failed)
        self.queue_panel.clear_completed.connect(self._on_clear_completed)
        self.queue_panel.clear_all.connect(self._on_clear_all)

        # マネージャー → UI
        mgr.item_added.connect(self._on_item_added)
        mgr.item_progress.connect(self._on_item_progress)
        mgr.item_status_changed.connect(self._on_item_status_changed)
        mgr.item_title_resolved.connect(self._on_item_title_resolved)
        mgr.item_finished.connect(self._on_item_finished)
        mgr.all_finished.connect(self._on_all_finished)
        mgr.queue_changed.connect(self._sync_ui_state)

    # =========================================================================
    # URL パネルハンドラ
    # =========================================================================

    def _on_url_submitted(self, url: str):
        """単一URLが送信された時の処理。"""
        from widgets.url_panel import UrlInputPanel

        if UrlInputPanel._is_playlist_url(url):
            self._batch_manager.add_playlist_items(url)
            self.progress_panel.set_status("プレイリストを展開中...")
        else:
            self._batch_manager.add_urls([url])

    def _on_bulk_urls_submitted(self, urls: list):
        """一括URLが送信された時の処理。"""
        from widgets.url_panel import UrlInputPanel

        playlist_urls = [u for u in urls if UrlInputPanel._is_playlist_url(u)]
        video_urls = [u for u in urls if not UrlInputPanel._is_playlist_url(u)]

        if video_urls:
            self._batch_manager.add_urls(video_urls)
        for purl in playlist_urls:
            self._batch_manager.add_playlist_items(purl)
        if playlist_urls:
            self.progress_panel.set_status(
                f"{len(playlist_urls)} 件のプレイリストを展開中..."
            )

    # =========================================================================
    # マネージャー → UI ハンドラ
    # =========================================================================

    @Slot(str, object)
    def _on_item_added(self, item_id: str, item: object):
        self.queue_panel.add_item(item_id, item)
        self._sync_ui_state()

    @Slot(str, float)
    def _on_item_progress(self, item_id: str, percent: float):
        self.queue_panel.update_item_progress(item_id, percent)
        self._sync_ui_state()

    @Slot(str, str)
    def _on_item_status_changed(self, item_id: str, status_value: str):
        self.queue_panel.update_item_status(item_id, ItemStatus(status_value))
        self._sync_ui_state()

    @Slot(str, str)
    def _on_item_title_resolved(self, item_id: str, title: str):
        self.queue_panel.update_item_title(item_id, title)
        item = self._batch_manager.find_item_by_id(item_id)
        if item:
            if item.duration:
                self.queue_panel.update_item_duration(item_id, item.duration)
            if item.filesize:
                self.queue_panel.update_item_filesize(item_id, item.filesize)

    @Slot(str, bool, str)
    def _on_item_finished(self, item_id: str, success: bool, message: str):
        # 失敗理由をキュー上に表示する（従来は✕アイコンのみでログを見るしかなかった）
        if not success and "キャンセル" not in message:
            self.queue_panel.set_item_error(item_id, message)
        self._sync_ui_state()

    @Slot(int, int)
    def _on_all_finished(self, success_count: int, fail_count: int):
        self.download_btn.setEnabled(True)
        self.download_btn.setText("ダウンロード開始")
        self.stop_btn.setVisible(False)
        self._sync_ui_state()

        if fail_count == 0:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("一括ダウンロード完了")
            msg_box.setIcon(QMessageBox.NoIcon)
            msg_box.setText(f"全 {success_count} 件のダウンロードが完了しました！")
            msg_box.setStyleSheet("QLabel { min-width: 420px; }")
            open_btn = msg_box.addButton("保存先を開く", QMessageBox.ActionRole)
            msg_box.addButton(QMessageBox.Ok)
            msg_box.exec()
            if msg_box.clickedButton() == open_btn:
                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(self.output_edit.text())
                )
        else:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("ダウンロード結果")
            msg_box.setIcon(QMessageBox.NoIcon)
            msg_box.setText(f"完了: {success_count} 件\n失敗: {fail_count} 件")
            msg_box.setInformativeText(
                "失敗したアイテムは「失敗を再試行」ボタンでリトライできます。"
            )
            msg_box.setStyleSheet("QLabel { min-width: 420px; }")
            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.exec()

    # =========================================================================
    # キューパネルハンドラ
    # =========================================================================

    def _on_remove_item(self, item_id: str):
        self._batch_manager.remove_item(item_id)
        self.queue_panel.remove_widget(item_id)
        self._sync_ui_state()

    def _on_retry_item(self, item_id: str):
        self._batch_manager.retry_item(item_id)
        if not self._batch_manager.is_running:
            self._start_batch_download()

    def _on_retry_all_failed(self):
        self._batch_manager.retry_all_failed()
        if not self._batch_manager.is_running:
            self._start_batch_download()

    def _on_clear_completed(self):
        if self._batch_manager.is_running:
            self.progress_panel.set_status(
                "ダウンロード中はクリアできません", is_error=True
            )
            return
        self._batch_manager.clear_completed()
        self.queue_panel.rebuild(self._batch_manager.items)
        self._sync_ui_state()

    def _on_clear_all(self):
        if self._batch_manager.is_running:
            self.progress_panel.set_status(
                "ダウンロード中はクリアできません", is_error=True
            )
            return
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("確認")
        msg_box.setText("キューの項目をすべてクリアしますか？")
        yes_btn = msg_box.addButton("Yes", QMessageBox.YesRole)
        no_btn = msg_box.addButton("No", QMessageBox.NoRole)
        msg_box.setDefaultButton(no_btn)
        msg_box.setIcon(QMessageBox.NoIcon)
        msg_box.exec()
        if msg_box.clickedButton() == yes_btn:
            self._batch_manager.clear_all()
            self.queue_panel.rebuild(self._batch_manager.items)
            self._sync_ui_state()

    # =========================================================================
    # ダウンロード制御
    # =========================================================================

    def _build_base_request(self) -> DownloadRequest:
        """現在のフォーマット設定からベースリクエストを構築する。"""
        return DownloadRequest(
            url="",
            output_path=self.output_edit.text(),
            format_type=self.format_panel.get_format_type(),
            resolution=self.format_panel.get_resolution(),
            audio_format=self.format_panel.get_audio_format(),
            bitrate=self.format_panel.get_bitrate(),
        )

    def _start_batch_download(self):
        """バッチダウンロードを開始するUI更新を行う。"""
        base_req = self._build_base_request()
        resolving = self._batch_manager.resolving_count

        self.download_btn.setEnabled(False)
        self.download_btn.setText("ダウンロード中...")
        self.stop_btn.setVisible(True)
        # タイトル取得が終わっていないアイテムがある場合は、その旨を伝える。
        # 取得完了後に自動でダウンロードが始まる。
        if resolving > 0:
            self.progress_panel.set_status(
                f"動画情報を取得中... ({resolving}件) 完了後に自動で開始します"
            )
        else:
            self.progress_panel.set_status("ダウンロード中...")
        self._batch_manager.start_all(base_req)

    def _on_start_batch(self):
        """「ダウンロード開始」ボタンのハンドラ。"""
        mgr = self._batch_manager

        if mgr.total_count == 0:
            url = self.url_panel.url_input.text().strip()
            if not url:
                self.progress_panel.set_status(
                    "URLを入力するか、キューに追加してください", is_error=True
                )
                return
            from widgets.url_panel import UrlInputPanel
            if not UrlInputPanel._validate_youtube_url(url):
                self.progress_panel.set_status(
                    "無効なURLです。YouTubeのURLを入力してください。", is_error=True
                )
                return
            self._batch_manager.add_urls([url])
            self.url_panel.url_input.clear()

        if mgr.pending_count == 0:
            self.progress_panel.set_status(
                "ダウンロード待ちのアイテムがありません", is_error=True
            )
            return

        self._start_batch_download()

    def _on_stop_all(self):
        """「全て停止」ボタンのハンドラ。"""
        self._batch_manager.stop_all()
        self.download_btn.setEnabled(True)
        self.download_btn.setText("ダウンロード開始")
        self.stop_btn.setVisible(False)
        self.progress_panel.set_status("ダウンロードを停止しました")

    # =========================================================================
    # 状態更新ヘルパー
    # =========================================================================

    def _sync_ui_state(self):
        """キューの現在の状態を元にUIを完全同期する。
        
        進捗バー・件数・ステータス文言の全てをこのメソッド一つで正確に更新する。
        イベントハンドラ内では、このメソッドを呼ぶだけでよい。
        """
        mgr = self._batch_manager
        total = mgr.total_count

        # 1. 全体進捗バーの更新
        if total == 0:
            self.progress_panel.update_progress(0, 0, 0)
        else:
            total_progress = sum(
                100.0 if item.status == ItemStatus.COMPLETED else
                item.display_progress if item.status == ItemStatus.DOWNLOADING else
                0.0
                for item in mgr.items
            )
            self.progress_panel.update_progress(
                total_progress / total, mgr.completed_count, total
            )

        # 2. キューの件数表示
        self.queue_panel.update_counts(
            total=total,
            completed=mgr.completed_count,
            failed=mgr.failed_count,
            is_running=mgr.is_running,
        )

        # 3. ステータス文言の自動同期（DL中は上書きしない）
        if mgr.is_running:
            return
        if total == 0:
            self.progress_panel.set_status("待機中")
        elif mgr.completed_count == total:
            self.progress_panel.set_status("すべてのダウンロードが完了しました！")
        elif mgr.failed_count > 0 and mgr.pending_count == 0:
            self.progress_panel.set_status(
                f"完了: {mgr.completed_count} 件 / 失敗: {mgr.failed_count} 件",
                is_error=True
            )
        elif mgr.pending_count > 0:
            self.progress_panel.set_status(f"ダウンロード開始待ち... ({mgr.pending_count}件)")
        else:
            self.progress_panel.set_status("待機中")

    # =========================================================================
    # イベントハンドラ
    # =========================================================================

    def eventFilter(self, source, event):
        if source == self.output_edit and event.type() == QEvent.Type.MouseButtonPress:
            self._on_browse()
            return True
        return super().eventFilter(source, event)

    def _on_browse(self):
        path = QFileDialog.getExistingDirectory(
            self, "保存先を選択", self.output_edit.text()
        )
        if path:
            self.output_edit.setText(path)

    def closeEvent(self, event):
        """全スレッドを安全に終了させてからウィンドウを閉じる。"""
        if self._batch_manager.is_running:
            logger.info("アプリ終了: ダウンロードを停止してスレッド終了を待機中...")
            self._batch_manager.stop_all()
        self._batch_manager.wait_all_workers(timeout_ms=5000)
        super().closeEvent(event)


# =============================================================================
# エントリーポイント
# =============================================================================

# 依存ツールのインストール方法（警告ダイアログで案内する）
_TOOL_INSTALL_HINTS = {
    "ffmpeg": "brew install ffmpeg",
}


def _warn_missing_tools(parent, missing_tools: list[str]) -> None:
    """必須の外部ツールが未検出の場合に警告ダイアログを表示する。

    ffmpeg が無いと音声変換も映像・音声のマージも失敗するため、
    ログだけでなくユーザーに直接伝える。
    """
    if not missing_tools:
        return

    names = "、".join(missing_tools)
    hints = "\n".join(
        f"    {tool}:  {_TOOL_INSTALL_HINTS.get(tool, '（README を参照してください）')}"
        for tool in missing_tools
    )
    logger.warning("必須ツール未検出をユーザーに通知します: %s", names)

    msg_box = QMessageBox(parent)
    msg_box.setWindowTitle("必要なツールが見つかりません")
    msg_box.setIcon(QMessageBox.Warning)
    msg_box.setText(f"{names} が見つかりませんでした。")
    msg_box.setInformativeText(
        "このままではダウンロードや音声変換に失敗します。\n"
        "ターミナルで以下を実行し、アプリを再起動してください:\n\n"
        f"{hints}"
    )
    msg_box.setStyleSheet("QLabel { min-width: 420px; }")
    msg_box.setStandardButtons(QMessageBox.Ok)
    msg_box.exec()


def _warn_stale_engine(parent) -> None:
    """同梱の yt-dlp が古い場合に警告する（.app 版のみ）。

    .app では yt-dlp を自己更新できないため、古いまま放置すると
    YouTubeの仕様変更で 403 が出てダウンロードが全滅する。
    原因が分からないまま失敗し続けるのを防ぐ。
    """
    if not getattr(sys, "frozen", False) or not is_yt_dlp_stale():
        return

    age = yt_dlp_age_days()
    logger.warning("同梱yt-dlpが古いためユーザーに通知します: %s", yt_dlp_version())

    msg_box = QMessageBox(parent)
    msg_box.setWindowTitle("ダウンロードエンジンが古くなっています")
    msg_box.setIcon(QMessageBox.Warning)
    msg_box.setText(
        f"同梱の yt-dlp ({yt_dlp_version()}) は約{age}日前のバージョンです。"
    )
    msg_box.setInformativeText(
        "YouTube側の仕様変更により、ダウンロードが「403 Forbidden」で\n"
        "失敗する可能性があります。\n\n"
        "解消するには、プロジェクトフォルダで以下を実行し、\n"
        "アプリを再ビルドしてください:\n\n"
        "    .venv/bin/pip install --upgrade yt-dlp\n"
        "    .venv/bin/pyinstaller YoutubeDownloader.spec --noconfirm"
    )
    msg_box.setStyleSheet("QLabel { min-width: 460px; }")
    msg_box.setStandardButtons(QMessageBox.Ok)
    msg_box.exec()


def run(missing_tools: Optional[list[str]] = None):
    # macOS標準ダイアログを日本語化するため、Cocoaの言語設定引数を追加
    argv = sys.argv.copy()
    if "-AppleLanguages" not in argv:
        argv.extend(["-AppleLanguages", "(ja)"])

    app = QApplication(argv)

    # Qt標準ダイアログ（ファイル選択等）の日本語化
    translator = QTranslator(app)
    trans_path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    if translator.load("qtbase_ja.qm", trans_path):
        app.installTranslator(translator)

    window = MainWindow()
    _update_worker = _YtDlpUpdateWorker(window)
    _update_worker.start()
    window.show()

    # ウィンドウ表示後に警告を出す（ダイアログが前面に来るように）
    _warn_missing_tools(window, missing_tools or [])
    _warn_stale_engine(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    run()
