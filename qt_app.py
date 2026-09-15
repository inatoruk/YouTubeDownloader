"""YouTube Downloader メインウィンドウ。

各UIパネルを組み合わせ、BatchDownloadManager との橋渡しを行う。
ビジネスロジックやUI構築の詳細は各パネルモジュールに委譲している。
"""

from __future__ import annotations

import sys
import os
import logging
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QScrollArea,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Slot, QEvent, QUrl, QTranslator, QLibraryInfo, QTimer
from PySide6.QtGui import (
    QColor, QPalette, QKeySequence, QShortcut, QDesktopServices, QFontDatabase, QFont, QFontInfo,
)

from downloader import (
    DownloadRequest, Downloader,
    is_yt_dlp_stale, yt_dlp_age_days, yt_dlp_version,
)
from queue_manager import BatchDownloadManager, DownloadItem, ItemStatus
from theme import Theme, build_global_stylesheet
from utils.worker import CancellableWorker
from utils.urls import classify_url
from widgets import UrlInputPanel, QueuePanel, FormatPanel, ProgressPanel
from widgets.surfaces import SidebarSurface, install_focus_style
from widgets.queue_panel import ElidedLabel

logger = logging.getLogger(__name__)


# =============================================================================
# yt-dlp 更新ワーカー
# =============================================================================
class _YtDlpUpdateWorker(CancellableWorker):
    """起動時にバックグラウンドで yt-dlp の更新を確認するワーカー。"""

    def run(self):
        try:
            if not self.is_cancelled():
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
        install_focus_style()
        self.setWindowTitle("YouTube Downloader")
        font = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        font.setFamily(QFontInfo(font).family())
        font.setStyleStrategy(QFont.PreferAntialias)
        self.setFont(font)
        self.resize(1200, 820)
        self.setMinimumSize(800, 600)

        # バッチマネージャー
        self._batch_manager = BatchDownloadManager(max_concurrent=2)
        self._closing = False
        self._stopping = False
        self._update_worker = None
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(50)
        self._shutdown_timer.timeout.connect(self._finish_close)

        Theme.configure(QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark)
        self._apply_palette()
        self._build_ui()
        self._setup_shortcuts()
        self._connect_signals()
        QApplication.styleHints().colorSchemeChanged.connect(self._on_color_scheme)
        self._sync_ui_state()
        self.url_panel.url_input.setFocus(Qt.OtherFocusReason)

    # =========================================================================
    # 初期化
    # =========================================================================

    def _apply_palette(self):
        """現在の外観に合わせてパレットとスタイルを適用する。"""
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
        central.setObjectName("Workspace")
        self.setCentralWidget(central)
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = SidebarSurface()
        self.sidebar = sidebar
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(264)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(20, 28, 20, 24)
        left.setSpacing(28)
        self.format_panel = FormatPanel()
        left.addWidget(self.format_panel)
        self._build_output_card(left)
        left.addStretch()
        shell.addWidget(sidebar)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 28, 28, 18)
        layout.setSpacing(20)
        self.url_panel = UrlInputPanel()
        layout.addWidget(self.url_panel)
        self.queue_panel = QueuePanel()
        layout.addWidget(self.queue_panel, 1)
        self.progress_panel = ProgressPanel()
        layout.addWidget(self.progress_panel)
        self._build_control_card(layout)
        shell.addWidget(content, 1)

    def _on_color_scheme(self, scheme):
        Theme.configure(scheme == Qt.ColorScheme.Dark)
        self._apply_palette()
        self.queue_panel.refresh_theme()
        self.progress_panel.refresh_theme()
        self.sidebar.update()

    def _build_output_card(self, parent_layout: QVBoxLayout):
        """保存先カードを構築する。"""
        card = QFrame()
        self.output_card = card
        card.setObjectName("OutputGroup")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 22, 0, 0)
        layout.setSpacing(12)

        title = QLabel("保存先")
        title.setObjectName("Title")
        layout.addWidget(title)

        self.output_edit = QLineEdit(card)
        self.output_edit.setReadOnly(True)
        self.output_edit.hide()
        row = QHBoxLayout()
        row.setSpacing(8)
        self.folder_label = ElidedLabel()
        self.folder_label.setAccessibleName("保存先")
        row.addWidget(self.folder_label, 1)
        change_btn = QPushButton("変更…")
        change_btn.setObjectName("link")
        change_btn.clicked.connect(self._on_browse)
        row.addWidget(change_btn)
        layout.addLayout(row)
        self.folder_path = ElidedLabel()
        self.folder_path.setObjectName("Secondary")
        layout.addWidget(self.folder_path)
        self.output_edit.textChanged.connect(self._update_folder_display)
        self.output_edit.setText(os.path.expanduser("~/Downloads"))
        parent_layout.addWidget(card)

    def _update_folder_display(self, path):
        name = os.path.basename(path.rstrip(os.sep)) or path
        self.folder_label.setText("ダウンロード" if path == os.path.expanduser("~/Downloads") else name)
        self.folder_label.setToolTip(path)
        home = os.path.expanduser("~")
        self.folder_path.setText("~" + path[len(home):] if path.startswith(home + os.sep) else path)

    def _build_control_card(self, parent_layout):
        card = QFrame()
        card.setObjectName("Footer")
        row = QHBoxLayout(card)
        row.setContentsMargins(0, 16, 0, 0)
        self.selection_summary = QLabel()
        self.selection_summary.setObjectName("Secondary")
        row.addWidget(self.selection_summary, 1)
        self.download_btn = QPushButton("ダウンロード開始")
        self.download_btn.setMinimumHeight(38)
        self.download_btn.clicked.connect(self._on_start_batch)
        self.stop_btn = QPushButton("すべて停止")
        self.stop_btn.setMinimumHeight(38)
        self.stop_btn.clicked.connect(self._on_stop_all)
        self.stop_btn.hide()
        row.addWidget(self.download_btn)
        row.addWidget(self.stop_btn)
        parent_layout.addWidget(card)
        for combo in (self.format_panel.resolution_combo, self.format_panel.format_combo,
                      self.format_panel.bitrate_combo):
            combo.currentTextChanged.connect(self._update_selection_summary)
        self.format_panel.video_radio.toggled.connect(self._update_selection_summary)
        self.output_edit.textChanged.connect(self._update_selection_summary)
        self._update_selection_summary()

    def _update_selection_summary(self, *_):
        panel = self.format_panel
        text = ("MP4 · " + panel.resolution_combo.currentText() if panel.get_format_type() == "video"
                else panel.get_audio_format() + (" · " + panel.get_bitrate() if panel.get_audio_format() == "MP3" else ""))
        self.selection_summary.setText(text)
        self.selection_summary.setToolTip(self.output_edit.text())

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
        self.url_panel.status_message.connect(self._show_status)
        self.url_panel.channel_confirmed.connect(self._intake_urls)
        self.url_panel.state_changed.connect(self._sync_import_controls)
        mgr.expansion_result.connect(self._on_expansion_result)

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
        mgr.item_metadata_changed.connect(self._on_item_metadata)

    # =========================================================================
    # URL パネルハンドラ
    # =========================================================================

    def _show_status(self, message, error=False):
        if not self._closing:
            self.progress_panel.set_status(message, error)

    def _on_expansion_result(self, operation_id, url, outcome, message):
        self._show_status(f'{message} ({url})', outcome in ('failed', 'empty'))

    def _on_url_submitted(self, url):
        self._intake_urls([url])

    def _on_bulk_urls_submitted(self, urls):
        self._intake_urls(urls)

    def _intake_urls(self, urls, auto_start=False):
        if self._closing:
            return
        videos, playlists, channels, errors = [], [], [], []
        for raw in urls:
            try:
                url, kind = classify_url(raw)
                {'video': videos, 'playlist': playlists, 'channel': channels}[kind].append(url)
            except ValueError as exc:
                errors.append(f'{raw}: {exc}')
        if videos:
            self._batch_manager.add_urls(videos)
        for url in playlists:
            self._batch_manager.add_playlist_items(url)
        for url in channels:
            self.url_panel.request_channel(url, auto_start)
        if auto_start and not self._batch_manager.is_running and (self._batch_manager.pending_count or self._batch_manager.expanding_count):
            self._start_batch_download()
        if errors:
            self._show_status(f'{len(errors)} 件の無効なURL: ' + ' / '.join(errors), True)

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
        item = self._batch_manager.find_item_by_id(item_id)
        if item:
            self.queue_panel.update_metadata(item)
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

    @Slot(str)
    def _on_item_metadata(self, item_id):
        item = self._batch_manager.find_item_by_id(item_id)
        if item:
            self.queue_panel.update_metadata(item)
            self._sync_ui_state()

    @Slot(str, bool, str)
    def _on_item_finished(self, item_id: str, success: bool, message: str):
        # 失敗理由をキュー上に表示する（従来は✕アイコンのみでログを見るしかなかった）
        if not success and "キャンセル" not in message:
            self.queue_panel.set_item_error(item_id, message)
        self._sync_ui_state()

    @Slot(int, int)
    def _on_all_finished(self, success_count: int, fail_count: int):
        if self._closing:
            return
        output_path = self._batch_manager.output_path
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
                    QUrl.fromLocalFile(output_path)
                )
        else:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("ダウンロード結果")
            msg_box.setIcon(QMessageBox.NoIcon)
            msg_box.setText(f"完了: {success_count} 件\n失敗（一覧取得を含む）: {fail_count} 件")
            msg_box.setInformativeText(
                "動画は「失敗を再試行」、一覧取得は対象URLを再追加してください。"
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
        if self._batch_manager.is_running or self._stopping:
            self.progress_panel.set_status(
                "ダウンロード中はクリアできません", is_error=True
            )
            return
        self._batch_manager.clear_completed()
        self.queue_panel.rebuild(self._batch_manager.items)
        self._sync_ui_state()

    def _on_clear_all(self):
        if self._batch_manager.is_running or self._stopping:
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
            self.url_panel.invalidate()
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
        if self._closing or self._stopping:
            return
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
        self._sync_ui_state()

    def _on_start_batch(self):
        """「ダウンロード開始」ボタンのハンドラ。"""
        mgr = self._batch_manager

        if self._closing or self._stopping:
            return
        if mgr.total_count == 0 and not mgr.expanding_count:
            url = self.url_panel.url_input.text().strip()
            if not url:
                self._show_status('URLを入力するか、キューに追加してください', True)
                return
            self._intake_urls([url], True)
            if self.url_panel._validate_youtube_url(url):
                self.url_panel.url_input.clear()
            return
        if mgr.pending_count == 0 and not mgr.expanding_count:
            self._show_status('ダウンロード待ちのアイテムがありません', True)
            return

        self._start_batch_download()

    def _on_stop_all(self):
        """「全て停止」ボタンのハンドラ。"""
        self.url_panel.cancel_auto_start()
        self._batch_manager.stop_all()
        self._stopping = bool(self._batch_manager.active_download_count)
        self._sync_ui_state()
        self._show_status('ダウンロードの停止処理中...' if self._stopping else 'ダウンロードを停止しました')

    # =========================================================================
    # 状態更新ヘルパー
    # =========================================================================

    def _sync_import_controls(self):
        if self._closing:
            return
        manager = self._batch_manager
        has_items = manager.total_count or manager.expanding_count or self.url_panel.busy
        self.queue_panel.clear_all_btn.setEnabled(bool(has_items) and not manager.is_running and not self._stopping)

    def _sync_ui_state(self):
        """キューの現在の状態を元にUIを完全同期する。
        
        進捗バー・件数・ステータス文言の全てをこのメソッド一つで正確に更新する。
        イベントハンドラ内では、このメソッドを呼ぶだけでよい。
        """
        if self._closing:
            return
        mgr = self._batch_manager
        if self._stopping and not mgr.active_download_count:
            self._stopping = False
        locked = mgr.is_running or self._stopping
        self.queue_panel.setEnabled(not self._stopping)
        self.output_card.setEnabled(not locked)
        self.format_panel.setEnabled(not locked)
        self.download_btn.setEnabled(not locked)
        self.download_btn.setText('停止処理中...' if self._stopping else 'ダウンロード中...' if mgr.is_running else 'ダウンロード開始')
        self.stop_btn.setVisible(mgr.is_running or self._stopping)
        self.stop_btn.setEnabled(not self._stopping)
        self.download_btn.setVisible(not (mgr.is_running or self._stopping))
        total = mgr.total_count

        # 1. 全体進捗バーの更新
        if total == 0:
            self.progress_panel.update_progress(0, 0, 0)
        else:
            total_progress = sum(
                100.0 if item.status == ItemStatus.COMPLETED else
                item.display_progress if item.status in (ItemStatus.DOWNLOADING, ItemStatus.CANCELLED, ItemStatus.FAILED) else
                0.0
                for item in mgr.items
            )
            self.progress_panel.update_progress(
                min(total_progress / total, 99.0) if mgr.completed_count != total or mgr.expanding_count or mgr.expansion_errors else 100.0, mgr.completed_count, total
            )

        self.progress_panel.update_capacity(mgr.items)

        # 2. キューの件数表示
        self.queue_panel.update_counts(
            total=total,
            completed=mgr.completed_count,
            failed=mgr.failed_count,
            is_running=locked,
        )

        self._sync_import_controls()

        # 3. ステータス文言の自動同期（DL中は上書きしない）
        if self._stopping:
            self.progress_panel.set_status("ダウンロードの停止処理中...")
            return
        if mgr.is_running:
            return
        if mgr.expansion_errors:
            self.progress_panel.set_status('一覧取得の失敗: ' + ' / '.join(f'{url}: {error}' for url, error in mgr.expansion_errors.items()), is_error=True)
        elif mgr.expanding_count:
            self.progress_panel.set_status(f'プレイリストを展開中... ({mgr.expanding_count}件)')
        elif total == 0:
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

    def _finish_close(self):
        update_busy = self._update_worker is not None and self._update_worker.isRunning()
        if self._batch_manager.busy or self.url_panel.busy or update_busy:
            return
        self._shutdown_timer.stop()
        self.close()

    def closeEvent(self, event):
        if not self._closing:
            self._closing = True
            self._batch_manager.shutdown()
            self.url_panel.shutdown()
            self.queue_panel.shutdown()
            if self._update_worker:
                self._update_worker.cancel()
            self.centralWidget().setEnabled(False)
            self.progress_panel.set_status('処理の終了を待っています')
        update_busy = self._update_worker is not None and self._update_worker.isRunning()
        if self._batch_manager.busy or self.url_panel.busy or update_busy:
            event.ignore()
            self._shutdown_timer.start()
        else:
            event.accept()


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
    window._update_worker = _YtDlpUpdateWorker(window)
    window._update_worker.start()
    window.show()

    # ウィンドウ表示後に警告を出す（ダイアログが前面に来るように）
    _warn_missing_tools(window, missing_tools or [])
    _warn_stale_engine(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    run()
