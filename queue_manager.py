"""一括ダウンロードのキュー管理とバッチ制御。

URLリストからダウンロードキューを構築し、最大N本の並列ワーカーで
ダウンロードを実行するオーケストレーションを提供する。

各アイテムは UUID で一意に識別される。インデックスの代わりに item_id を
通じて UI と通信することで、リスト操作（削除・並び替え）後の不整合を防ぐ。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence

from PySide6.QtCore import QObject, Signal, Slot, QThread

from downloader import DownloadRequest, Downloader

logger = logging.getLogger(__name__)


class ItemStatus(Enum):
    """ダウンロードアイテムのステータス。"""
    PENDING = "pending"
    RESOLVING = "resolving"      # タイトル取得中
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadItem:
    """キュー内の1ダウンロードアイテム。

    id フィールドは UUID4 で自動生成され、リスト操作後も不変。
    """
    url: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""              # 動画タイトル（取得後に更新）
    status: ItemStatus = ItemStatus.PENDING
    progress: float = 0.0        # 0.0〜100.0
    error: Optional[str] = None
    filepath: Optional[str] = None
    duration: Optional[str] = None  # 動画の長さ（表示用）
    filesize: Optional[str] = None  # ファイルサイズ（表示用）

    # 複数ファイル（映像＋音声など）のダウンロード時に進捗が逆行するのを防ぎ、表示進捗を合成する
    _max_raw_progress: float = 0.0
    _current_pass: int = 0

    @property
    def display_progress(self) -> float:
        """UI表示用に逆行を防ぎ、映像80% + 音声20%等として合成した仮想進捗 (0.0〜100.0) を返す"""
        if self.status == ItemStatus.COMPLETED:
            return 100.0
            
        # 値が10%以上下がったら、次のファイル（音声等）のダウンロードが始まったと判定してパスを切り替え
        if self.progress < self._max_raw_progress - 10.0:
            self._current_pass = 1
            self._max_raw_progress = self.progress
            
        self._max_raw_progress = max(self._max_raw_progress, self.progress)
        
        if self._current_pass == 0:
            # 1つめのファイル（映像は非常に重いので90%のウェイト）
            return self.progress * 0.9
        else:
            # 2つめのファイル（音声は残り10%のウェイト）
            return 90.0 + (self.progress * 0.1)


class _SingleWorker(QThread):
    """1本分のダウンロードを実行するワーカースレッド。"""
    # シグナルのキーはインデックスではなく item_id（str）
    progress = Signal(str, dict)          # (item_id, progress_data)
    status_changed = Signal(str, str)     # (item_id, status_string)
    finished_item = Signal(str, bool, str)  # (item_id, success, message_or_filepath)

    def __init__(self, item_id: str, request: DownloadRequest, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.request = request
        self._downloader = Downloader(auto_update=False)
        self._cancelled = False

    def cancel(self):
        """キャンセルフラグを立てる。"""
        self._cancelled = True

    def run(self):
        if self._cancelled:
            self.finished_item.emit(self.item_id, False, "キャンセルされました")
            return

        try:
            self.status_changed.emit(self.item_id, ItemStatus.DOWNLOADING.value)

            def progress_hook(d):
                if self._cancelled:
                    raise Exception("キャンセルされました")
                self.progress.emit(self.item_id, d)

            filepath = self._downloader.download(
                request=self.request,
                progress_hooks=[progress_hook],
            )
            if self._cancelled:
                self.finished_item.emit(self.item_id, False, "キャンセルされました")
            else:
                self.finished_item.emit(self.item_id, True, filepath or "ダウンロード完了")
        except Exception as e:
            if self._cancelled:
                self.finished_item.emit(self.item_id, False, "キャンセルされました")
            else:
                logger.error("Download error for item %s: %s", self.item_id, e)
                self.finished_item.emit(self.item_id, False, str(e))


class _InfoWorker(QThread):
    """動画情報をプリフェッチするワーカースレッド。"""
    info_fetched = Signal(str, dict)    # (item_id, info_dict)
    info_failed = Signal(str, str)      # (item_id, error_message)

    def __init__(self, item_id: str, url: str, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.url = url
        self._downloader = Downloader(auto_update=False)

    def run(self):
        try:
            info = self._downloader.fetch_info(self.url)
            if info:
                self.info_fetched.emit(self.item_id, info)
            else:
                self.info_failed.emit(self.item_id, "情報を取得できませんでした")
        except Exception as e:
            logger.error("Info fetch error for item %s: %s", self.item_id, e)
            self.info_failed.emit(self.item_id, str(e))


class BatchDownloadManager(QObject):
    """バッチダウンロードのオーケストレーション。

    URLリストからキューを構築し、指定された並列数で
    ダウンロードを順次実行する。

    【設計方針】
    - 各アイテムは UUID（item_id）で一意に識別する
    - 全シグナルは index ではなく item_id を使用する
    - これにより clear_completed / remove_item 後もUI/ワーカーの対応が壊れない
    """

    # --- シグナル（item_id は str） ---
    item_added = Signal(str, object)           # (item_id, DownloadItem)
    item_progress = Signal(str, float)         # (item_id, percent)
    item_status_changed = Signal(str, str)     # (item_id, status_value)
    item_title_resolved = Signal(str, str)     # (item_id, title)
    item_finished = Signal(str, bool, str)     # (item_id, success, message)
    all_finished = Signal(int, int)            # (success_count, fail_count)
    queue_changed = Signal()                   # キュー内容が変化した

    def __init__(self, max_concurrent: int = 2, parent=None):
        super().__init__(parent)
        self._items: list[DownloadItem] = []
        self._max_concurrent = max(1, max_concurrent)
        self._active_workers: dict[str, _SingleWorker] = {}   # item_id -> worker
        self._info_workers: dict[str, _InfoWorker] = {}        # item_id -> worker
        # 複数プレイリストの同時展開に対応するためリストで管理（#3修正）
        self._playlist_workers: list[_PlaylistExpandWorker] = []
        self._is_running = False
        self._base_request: Optional[DownloadRequest] = None

    # --- プロパティ ---

    @property
    def items(self) -> list[DownloadItem]:
        return self._items

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def total_count(self) -> int:
        return len(self._items)

    @property
    def completed_count(self) -> int:
        return sum(1 for item in self._items if item.status == ItemStatus.COMPLETED)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self._items if item.status == ItemStatus.FAILED)

    @property
    def pending_count(self) -> int:
        return sum(
            1 for item in self._items
            if item.status in (ItemStatus.PENDING, ItemStatus.RESOLVING)
        )

    @property
    def resolving_count(self) -> int:
        """タイトル取得中（RESOLVING）のアイテム数。

        この数が0になるまでバッチは「完了」とみなさない。
        追加直後（情報取得中）に開始した場合、ディスパッチ対象が
        まだ存在しないだけで、待てば流れ始めるため。
        """
        return sum(1 for item in self._items if item.status == ItemStatus.RESOLVING)

    # --- キュー操作 ---

    def find_item_by_id(self, item_id: str) -> Optional[DownloadItem]:
        """IDでアイテムを検索する（外部からも参照可能）。"""
        for item in self._items:
            if item.id == item_id:
                return item
        return None

    def add_urls(self, urls: Sequence[str]) -> list[str]:
        """URLリストをキューに追加する。追加された item_id リストを返す。"""
        added_ids: list[str] = []
        existing_urls = {item.url for item in self._items}

        for raw_url in urls:
            url = raw_url.strip()
            if not url:
                continue
            if url in existing_urls:
                logger.info("Duplicate URL skipped: %s", url)
                continue

            item = DownloadItem(url=url)  # id は自動生成
            self._items.append(item)
            existing_urls.add(url)
            added_ids.append(item.id)
            self.item_added.emit(item.id, item)

            # バックグラウンドでタイトル取得
            self._start_info_fetch(item.id, url)

        if added_ids:
            self.queue_changed.emit()
        return added_ids

    def add_playlist_items(self, playlist_url: str) -> None:
        """プレイリストURLを展開してキューに追加する。

        展開処理はバックグラウンドスレッドで行われ、個別の動画URLがキューに追加される。
        複数プレイリストの同時展開に対応するためリストで管理する（#3修正）。
        """
        worker = _PlaylistExpandWorker(playlist_url, self)
        worker.urls_extracted.connect(self._on_playlist_expanded)
        worker.expand_failed.connect(self._on_playlist_expand_failed)
        # 完了後にリストから除去してメモリを解放
        worker.finished.connect(lambda: self._cleanup_playlist_worker(worker))
        self._playlist_workers.append(worker)
        worker.start()

    def _cleanup_playlist_worker(self, worker: _PlaylistExpandWorker) -> None:
        """プレイリスト展開ワーカーをリストから除去してクリーンアップする。"""
        try:
            self._playlist_workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    def remove_item(self, item_id: str) -> None:
        """キューからアイテムを削除する。ダウンロード中のものはキャンセルする。"""
        item = self.find_item_by_id(item_id)
        if item is None:
            return
        if item.status == ItemStatus.DOWNLOADING and item_id in self._active_workers:
            self._cancel_worker(item_id)
            
        # リストから完全に削除する
        self._items = [i for i in self._items if i.id != item_id]
        
        self.item_status_changed.emit(item_id, ItemStatus.CANCELLED.value)
        self.queue_changed.emit()

    def clear_completed(self) -> None:
        """完了（COMPLETED）したアイテムのみをキューから除去する。

        item_id ベース管理のため、clear後もアクティブなワーカー辞書は正常に機能する。
        """
        self._items = [item for item in self._items if item.status != ItemStatus.COMPLETED]
        self.queue_changed.emit()

    def clear_all(self) -> None:
        """全てのアイテムをキューから除去する。ダウンロード中のものがあれば停止する。"""
        self.stop_all()
        self._items.clear()
        self.queue_changed.emit()

    # --- ダウンロード制御 ---

    def start_all(self, base_request: DownloadRequest) -> None:
        """全ての待機中アイテムのダウンロードを開始する。"""
        self._base_request = base_request
        self._is_running = True
        self._dispatch_next()

    def stop_all(self) -> None:
        """全てのダウンロードを停止する。"""
        self._is_running = False
        for item_id in list(self._active_workers.keys()):
            self._cancel_worker(item_id)

    def wait_all_workers(self, timeout_ms: int = 5000) -> None:
        """全てのアクティブワーカーの終了を待機する（アプリ終了時に使用）。

        アクティブな _SingleWorker スレッドが Qt オブジェクト破棄後も
        走り続けることによる segfault を防ぐ（#9修正）。

        Args:
            timeout_ms: 各ワーカーへの最大待機時間（ms）。超過した場合は強制終了。
        """
        for worker in list(self._active_workers.values()):
            if worker.isRunning():
                if not worker.wait(timeout_ms):
                    logger.warning(
                        "Worker %s がタイムアウトしました、強制終了します", worker.item_id
                    )
                    worker.terminate()
                    worker.wait(1000)

    def retry_item(self, item_id: str) -> None:
        """失敗したアイテムをリトライする。"""
        item = self.find_item_by_id(item_id)
        if item and item.status in (ItemStatus.FAILED, ItemStatus.CANCELLED):
            item.status = ItemStatus.PENDING
            item.progress = 0.0
            item.error = None
            self.item_status_changed.emit(item_id, ItemStatus.PENDING.value)
            self.item_progress.emit(item_id, 0.0)
            if self._is_running:
                self._dispatch_next()

    def retry_all_failed(self) -> None:
        """全ての失敗アイテムをリトライする。"""
        for item in self._items:
            if item.status == ItemStatus.FAILED:
                item.status = ItemStatus.PENDING
                item.progress = 0.0
                item.error = None
                self.item_status_changed.emit(item.id, ItemStatus.PENDING.value)
        if self._is_running:
            self._dispatch_next()

    # --- 内部メソッド ---

    def _start_info_fetch(self, item_id: str, url: str) -> None:
        """バックグラウンドで動画タイトルを取得する。"""
        if item_id in self._info_workers:
            return
        item = self.find_item_by_id(item_id)
        if item is None:
            return
        item.status = ItemStatus.RESOLVING
        self.item_status_changed.emit(item_id, ItemStatus.RESOLVING.value)

        worker = _InfoWorker(item_id, url, self)
        worker.info_fetched.connect(self._on_info_fetched)
        worker.info_failed.connect(self._on_info_failed)
        worker.finished.connect(lambda: self._cleanup_info_worker(item_id))
        self._info_workers[item_id] = worker
        worker.start()

    def _cleanup_info_worker(self, item_id: str) -> None:
        """情報取得ワーカーをクリーンアップする。

        バッチ実行中にタイトル取得が完了した場合、この時点でアイテムは
        RESOLVING から PENDING に遷移済みなので、ここでディスパッチを促す。
        （info_fetched/info_failed はこのスロットより先に配送される）
        アイテムが途中で削除されていた場合も、ここを通ることで
        「RESOLVING待ちのまま止まる」状態を防げる。
        """
        worker = self._info_workers.pop(item_id, None)
        if worker:
            worker.deleteLater()
        if self._is_running:
            self._dispatch_next()

    @Slot(str, dict)
    def _on_info_fetched(self, item_id: str, info: dict) -> None:
        """タイトル取得成功時の処理。"""
        item = self.find_item_by_id(item_id)
        if item is None:
            return
        item.title = info.get("title", "")
        duration = info.get("duration")
        if duration:
            minutes, seconds = divmod(int(duration), 60)
            hours, minutes = divmod(minutes, 60)
            if hours:
                item.duration = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                item.duration = f"{minutes}:{seconds:02d}"
        
        item.filesize = info.get("filesize")
        if item.status == ItemStatus.RESOLVING:
            item.status = ItemStatus.PENDING
            self.item_status_changed.emit(item_id, ItemStatus.PENDING.value)
        self.item_title_resolved.emit(item_id, item.title)

    @Slot(str, str)
    def _on_info_failed(self, item_id: str, error: str) -> None:
        """タイトル取得失敗時の処理（ダウンロード自体は許可する）。"""
        item = self.find_item_by_id(item_id)
        if item and item.status == ItemStatus.RESOLVING:
            item.status = ItemStatus.PENDING
            self.item_status_changed.emit(item_id, ItemStatus.PENDING.value)
        logger.warning("Could not fetch info for item %s: %s", item_id, error)

    def _dispatch_next(self) -> None:
        """次の待機中アイテムをワーカーに割り当てる。"""
        if not self._is_running or not self._base_request:
            return

        while len(self._active_workers) < self._max_concurrent:
            next_item = self._find_next_pending()
            if next_item is None:
                break
            self._start_download(next_item.id)

        # タイトル取得中のアイテムが残っている間は「完了」と判定しない。
        # 情報取得が終われば PENDING に遷移し、_cleanup_info_worker から
        # 再度 _dispatch_next が呼ばれてダウンロードが始まる。
        if self.resolving_count > 0:
            return

        # 全ワーカーが終了していてペンディングもない場合、完了通知
        if not self._active_workers and self._find_next_pending() is None:
            self._is_running = False
            self.all_finished.emit(self.completed_count, self.failed_count)

    def _find_next_pending(self) -> Optional[DownloadItem]:
        """次の待機中アイテムを返す。"""
        for item in self._items:
            if item.status == ItemStatus.PENDING and item.id not in self._active_workers:
                return item
        return None

    def _start_download(self, item_id: str) -> None:
        """指定IDのダウンロードを開始する。"""
        if item_id in self._active_workers:
            return
        item = self.find_item_by_id(item_id)
        if item is None:
            return
        request = DownloadRequest(
            url=item.url,
            output_path=self._base_request.output_path,
            format_type=self._base_request.format_type,
            resolution=self._base_request.resolution,
            audio_format=self._base_request.audio_format,
            bitrate=self._base_request.bitrate,
        )

        worker = _SingleWorker(item_id, request, self)
        worker.progress.connect(self._on_worker_progress)
        worker.status_changed.connect(self._on_worker_status)
        worker.finished_item.connect(self._on_worker_finished)
        self._active_workers[item_id] = worker

        item.status = ItemStatus.DOWNLOADING
        self.item_status_changed.emit(item_id, ItemStatus.DOWNLOADING.value)
        worker.start()

    def _cancel_worker(self, item_id: str) -> None:
        """ワーカーをキャンセルする。"""
        worker = self._active_workers.get(item_id)
        if worker:
            worker.cancel()
            # ワーカーの終了は finished_item シグナルで処理

    @Slot(str, dict)
    def _on_worker_progress(self, item_id: str, data: dict) -> None:
        """ワーカーの進捗更新。"""
        if data.get("status") == "downloading":
            try:
                p_str = data.get("_percent_str", "0%").replace("%", "")
                percent = float(p_str)
                item = self.find_item_by_id(item_id)
                if item:
                    item.progress = percent
                    self.item_progress.emit(item_id, item.display_progress)
            except ValueError:
                pass
        elif data.get("status") == "finished":
            item = self.find_item_by_id(item_id)
            if item:
                item.progress = 100.0
                self.item_progress.emit(item_id, item.display_progress)

    @Slot(str, str)
    def _on_worker_status(self, item_id: str, status: str) -> None:
        """ワーカーのステータス変更。"""
        item = self.find_item_by_id(item_id)
        if item:
            item.status = ItemStatus(status)
        self.item_status_changed.emit(item_id, status)

    @Slot(str, bool, str)
    def _on_worker_finished(self, item_id: str, success: bool, message: str) -> None:
        """ワーカーの完了処理。"""
        worker = self._active_workers.pop(item_id, None)
        if worker:
            worker.deleteLater()

        item = self.find_item_by_id(item_id)
        if item:
            if success:
                item.status = ItemStatus.COMPLETED
                item.progress = 100.0
                item.filepath = message
            else:
                if "キャンセル" in message:
                    item.status = ItemStatus.CANCELLED
                else:
                    item.status = ItemStatus.FAILED
                    item.error = message
            self.item_status_changed.emit(item_id, item.status.value)

        self.item_finished.emit(item_id, success, message)

        # 次のアイテムをディスパッチ
        self._dispatch_next()

    @Slot(list)
    def _on_playlist_expanded(self, urls: list) -> None:
        """プレイリスト展開完了時の処理。"""
        self.add_urls(urls)

    @Slot(str)
    def _on_playlist_expand_failed(self, error: str) -> None:
        """プレイリスト展開失敗時の処理。"""
        logger.error("Playlist expansion failed: %s", error)


class _PlaylistExpandWorker(QThread):
    """プレイリストURLから個別の動画URLを抽出するワーカー。"""
    urls_extracted = Signal(list)
    expand_failed = Signal(str)

    def __init__(self, playlist_url: str, parent=None):
        super().__init__(parent)
        self.playlist_url = playlist_url
        self._downloader = Downloader(auto_update=False)

    def run(self):
        try:
            urls = self._downloader.extract_playlist_urls(self.playlist_url)
            self.urls_extracted.emit(urls)
        except Exception as e:
            logger.error("Playlist extraction error: %s", e)
            self.expand_failed.emit(str(e))
