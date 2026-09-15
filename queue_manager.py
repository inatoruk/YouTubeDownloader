"""一括ダウンロードのキュー管理とバッチ制御。

URLリストからダウンロードキューを構築し、最大N本の並列ワーカーで
ダウンロードを実行するオーケストレーションを提供する。

各アイテムは UUID で一意に識別される。インデックスの代わりに item_id を
通じて UI と通信することで、リスト操作（削除・並び替え）後の不整合を防ぐ。
"""

from __future__ import annotations

import logging
from pathlib import Path
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence

from PySide6.QtCore import QObject, Signal, Slot, QThread

from downloader import DownloadCancelled, DownloadRequest, Downloader
from utils.worker import CancellableWorker
from utils.urls import classify_url

logger = logging.getLogger(__name__)


def format_bytes(value):
    if value is None:
        return "—"
    number = max(0, value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{number:.0f} B" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024


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

    uploader: str = ""
    thumbnail_url: str = ""
    filesize_bytes: Optional[int] = None
    stream_bytes: dict[str, int] = field(default_factory=dict)
    stream_totals: dict[str, Optional[int]] = field(default_factory=dict)
    expected_streams: set[str] = field(default_factory=set)
    phase: str = ""

    @property
    def downloaded_bytes(self):
        return sum(self.stream_bytes.values())

    @property
    def transfer_total_bytes(self):
        if not self.stream_totals:
            return self.filesize_bytes
        if self.expected_streams and not self.expected_streams.issubset(self.stream_totals):
            return None
        values = list(self.stream_totals.values())
        return sum(values) if all(value is not None for value in values) else None

    def record_transfer(self, data):
        info = data.get('info_dict') or {}
        formats = info.get('requested_downloads') or info.get('requested_formats') or []
        for fmt in formats:
            if fmt.get('format_id') is not None:
                key = str(fmt['format_id'])
                self.expected_streams.add(key)
                total = fmt.get('filesize') or fmt.get('filesize_approx')
                if isinstance(total, (int, float)) and total >= 0:
                    self.stream_totals.setdefault(key, int(total))
        key = str(info.get('format_id') or data.get('filename') or 'media')
        received = data.get('downloaded_bytes')
        total = data.get('total_bytes') or data.get('total_bytes_estimate')
        if isinstance(received, (int, float)) and received >= 0:
            self.stream_bytes[key] = max(self.stream_bytes.get(key, 0), int(received))
        if data.get('status') == 'finished' and isinstance(received, (int, float)):
            total = received
        if isinstance(total, (int, float)) and total >= 0:
            self.stream_totals[key] = max(int(total), self.stream_bytes.get(key, 0))
        else:
            self.stream_totals.setdefault(key, None)
        self.phase = '変換・結合中' if data.get('status') == 'finished' else '保存中'

    # 複数ファイル（映像＋音声など）のダウンロード時に進捗が逆行するのを防ぎ、表示進捗を合成する
    _max_raw_progress: float = 0.0
    _current_pass: int = 0

    _display_progress: float = 0.0

    @property
    def display_progress(self) -> float:
        return 100.0 if self.status == ItemStatus.COMPLETED else self._display_progress

    def update_progress(self, value: float):
        self.progress = max(0.0, min(100.0, value))
        if self.progress < self._max_raw_progress - 10.0:
            self._current_pass = 1
            self._max_raw_progress = 0.0
        self._max_raw_progress = max(self._max_raw_progress, self.progress)
        value = self.progress * 0.9 if self._current_pass == 0 else 90.0 + self.progress * 0.1
        self._display_progress = min(99.0, max(self._display_progress, value))

    def reset_for_retry(self):
        self.status = ItemStatus.PENDING
        self.progress = self._max_raw_progress = self._display_progress = 0.0
        self._current_pass = 0
        self.error = self.filepath = None
        self.stream_bytes.clear()
        self.stream_totals.clear()
        self.expected_streams.clear()
        self.phase = ""


class _SingleWorker(CancellableWorker):
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

    def run(self):
        if self.is_cancelled():
            self.finished_item.emit(self.item_id, False, "キャンセルされました")
            return

        try:
            self.status_changed.emit(self.item_id, ItemStatus.DOWNLOADING.value)

            def progress_hook(d):
                if self.is_cancelled():
                    # 専用例外にすることでリトライループに飲まれない
                    raise DownloadCancelled("キャンセルされました")
                self.progress.emit(self.item_id, d)

            filepath = self._downloader.download(
                request=self.request,
                progress_hooks=[progress_hook],
                is_cancelled=self.is_cancelled,
            )
            if self.is_cancelled():
                self.finished_item.emit(self.item_id, False, "キャンセルされました")
            else:
                self.finished_item.emit(self.item_id, True, filepath or "ダウンロード完了")
        except DownloadCancelled:
            self.finished_item.emit(self.item_id, False, "キャンセルされました")
        except Exception as e:
            if self.is_cancelled():
                self.finished_item.emit(self.item_id, False, "キャンセルされました")
            else:
                logger.error("Download error for item %s: %s", self.item_id, e)
                self.finished_item.emit(self.item_id, False, str(e))


class _InfoWorker(CancellableWorker):
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
            info = self._downloader.fetch_info(self.url, self.is_cancelled)
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
    item_metadata_changed = Signal(str)
    item_progress = Signal(str, float)         # (item_id, percent)
    item_status_changed = Signal(str, str)     # (item_id, status_value)
    item_title_resolved = Signal(str, str)     # (item_id, title)
    item_finished = Signal(str, bool, str)     # (item_id, success, message)
    all_finished = Signal(int, int)            # (success_count, fail_count)
    expansion_result = Signal(str, str, str, str)  # id, URL, outcome, message
    queue_changed = Signal()                   # キュー内容が変化した

    # タイトル取得の同時実行数。チャンネル展開で数百件が一度に入っても
    # スレッドとネットワーク接続が爆発しないよう上限を設ける。
    MAX_INFO_WORKERS = 4

    def __init__(self, max_concurrent: int = 2, parent=None):
        super().__init__(parent)
        self._items: list[DownloadItem] = []
        self._max_concurrent = max(1, max_concurrent)
        self._active_workers: dict[str, _SingleWorker] = {}   # item_id -> worker
        self._info_workers: dict[str, _InfoWorker] = {}        # item_id -> worker
        # 取得待ちの (item_id, url)。MAX_INFO_WORKERS を超えた分はここで待機する
        self._info_queue: list[tuple[str, str]] = []
        # 複数プレイリストの同時展開に対応するためリストで管理（#3修正）
        self._playlist_workers: list[_PlaylistExpandWorker] = []
        self._is_running = False
        self._closing = False
        self._generation = 0
        self._expansion_errors: dict[str, str] = {}
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
        if self._closing:
            return []
        added_ids: list[str] = []
        existing_urls = {item.url for item in self._items}

        for raw_url in urls:
            url, kind = classify_url(raw_url)
            if kind != "video":
                raise ValueError("動画URLを入力してください")
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

    @property
    def expanding_count(self):
        return sum(w.generation == self._generation for w in self._playlist_workers)

    @property
    def busy(self):
        return bool(self._active_workers or self._info_workers or self._playlist_workers)

    @property
    def active_download_count(self):
        return len(self._active_workers)

    @property
    def expansion_errors(self):
        return dict(self._expansion_errors)

    @property
    def output_path(self):
        return self._base_request.output_path if self._base_request else ""

    def shutdown(self):
        self._closing = True
        self.stop_all()
        self._generation += 1
        self._expansion_errors.clear()
        for worker in [*self._info_workers.values(), *self._playlist_workers]:
            worker.cancel()
        self._info_queue.clear()

    def add_playlist_items(self, playlist_url: str) -> None:
        if self._closing:
            return
        playlist_url, kind = classify_url(playlist_url)
        if kind != 'playlist':
            raise ValueError('プレイリストURLを入力してください')
        self._expansion_errors.pop(playlist_url, None)
        worker = _PlaylistExpandWorker(playlist_url, self)
        worker.generation = self._generation
        worker.operation_id = str(uuid.uuid4())
        worker.urls_extracted.connect(self._on_playlist_expanded)
        worker.expand_failed.connect(self._on_playlist_expand_failed)
        worker.finished.connect(self._cleanup_playlist_worker)
        self._playlist_workers.append(worker)
        self.expansion_result.emit(worker.operation_id, playlist_url, 'started', 'プレイリストを展開中...')
        worker.start()
        self.queue_changed.emit()

    @Slot()
    def _cleanup_playlist_worker(self):
        worker = self.sender()
        if worker in self._playlist_workers:
            self._playlist_workers.remove(worker)
            worker.deleteLater()
        self._dispatch_next()
        self.queue_changed.emit()

    def remove_item(self, item_id: str) -> None:
        """キューからアイテムを削除する。ダウンロード中のものはキャンセルする。"""
        item = self.find_item_by_id(item_id)
        if item is None:
            return
        if item.status == ItemStatus.DOWNLOADING and item_id in self._active_workers:
            self._cancel_worker(item_id)

        # タイトル取得の待機列からも除去する（起動済みのものは
        # _pump_info_queue 側でアイテム不在としてスキップされる）
        self._info_queue = [q for q in self._info_queue if q[0] != item_id]

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
        self._generation += 1
        self._expansion_errors.clear()
        for worker in [*self._info_workers.values(), *self._playlist_workers]:
            worker.cancel()
        self._info_queue.clear()
        self._items.clear()
        self.queue_changed.emit()

    # --- ダウンロード制御 ---

    def start_all(self, base_request: DownloadRequest) -> None:
        """全ての待機中アイテムのダウンロードを開始する。"""
        if self._closing:
            return
        self._base_request = base_request
        self._is_running = True
        self._dispatch_next()

    def stop_all(self) -> None:
        """全てのダウンロードを停止する。"""
        self._is_running = False
        for item_id in list(self._active_workers.keys()):
            self._cancel_worker(item_id)

    def wait_all_workers(self, timeout_ms: int = 5000) -> bool:
        """Bounded wait for callers outside the GUI; never terminate threads."""
        workers = [*self._active_workers.values(), *self._info_workers.values(), *self._playlist_workers]
        return all([worker.wait(timeout_ms) for worker in workers])

    def retry_item(self, item_id: str) -> None:
        """失敗したアイテムをリトライする。"""
        item = self.find_item_by_id(item_id)
        if item and item.status in (ItemStatus.FAILED, ItemStatus.CANCELLED):
            item.reset_for_retry()
            self.item_status_changed.emit(item_id, ItemStatus.PENDING.value)
            self.item_progress.emit(item_id, 0.0)
            if self._is_running:
                self._dispatch_next()

    def retry_all_failed(self) -> None:
        """全ての失敗アイテムをリトライする。"""
        for item in self._items:
            if item.status == ItemStatus.FAILED:
                item.reset_for_retry()
                self.item_progress.emit(item.id, 0.0)
                self.item_status_changed.emit(item.id, ItemStatus.PENDING.value)
        if self._is_running:
            self._dispatch_next()

    # --- 内部メソッド ---

    def _start_info_fetch(self, item_id: str, url: str) -> None:
        """タイトル取得を予約する。

        実際の起動は _pump_info_queue が MAX_INFO_WORKERS の範囲で行う。
        以前はURL1件ごとに無制限にスレッドを起動しており、チャンネル展開で
        数百件が入るとスレッドと同時接続が爆発していた。
        """
        if item_id in self._info_workers:
            return
        if any(queued_id == item_id for queued_id, _ in self._info_queue):
            return
        item = self.find_item_by_id(item_id)
        if item is None:
            return

        # 待機中もRESOLVING扱いにしておくことで、取得完了前に
        # バッチが「完了」と誤判定されるのを防ぐ
        item.status = ItemStatus.RESOLVING
        self.item_status_changed.emit(item_id, ItemStatus.RESOLVING.value)

        self._info_queue.append((item_id, url))
        self._pump_info_queue()

    def _pump_info_queue(self) -> None:
        """上限に達するまで、待機中のタイトル取得を開始する。"""
        while not self._closing and self._info_queue and len(self._info_workers) < self.MAX_INFO_WORKERS:
            item_id, url = self._info_queue.pop(0)
            # 待機中に削除されたアイテムはスキップ
            if self.find_item_by_id(item_id) is None:
                continue
            if item_id in self._info_workers:
                continue

            worker = _InfoWorker(item_id, url, self)
            worker.info_fetched.connect(self._on_info_fetched)
            worker.info_failed.connect(self._on_info_failed)
            worker.finished.connect(self._cleanup_info_worker)
            self._info_workers[item_id] = worker
            worker.start()

    @Slot()
    def _cleanup_info_worker(self) -> None:
        """情報取得ワーカーをクリーンアップする。

        バッチ実行中にタイトル取得が完了した場合、この時点でアイテムは
        RESOLVING から PENDING に遷移済みなので、ここでディスパッチを促す。
        （info_fetched/info_failed はこのスロットより先に配送される）
        アイテムが途中で削除されていた場合も、ここを通ることで
        「RESOLVING待ちのまま止まる」状態を防げる。
        """
        sender = self.sender()
        worker = self._info_workers.pop(sender.item_id, None)
        if worker:
            worker.deleteLater()
        # 空いた枠で待機中の取得を開始する
        self._pump_info_queue()
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
        item.filesize_bytes = info.get("filesize_bytes")
        item.uploader = info.get("uploader", "")
        item.thumbnail_url = info.get("thumbnail", "")
        self.item_metadata_changed.emit(item_id)
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
        if self.resolving_count > 0 or self.expanding_count > 0:
            return

        # 全ワーカーが終了していてペンディングもない場合、完了通知
        if not self._active_workers and self._find_next_pending() is None:
            self._is_running = False
            self.all_finished.emit(self.completed_count, self.failed_count + len(self._expansion_errors))

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
        worker.finished.connect(self._cleanup_download_worker)
        self._active_workers[item_id] = worker

        item.status = ItemStatus.DOWNLOADING
        self.item_status_changed.emit(item_id, ItemStatus.DOWNLOADING.value)
        worker.start()

    def _cancel_worker(self, item_id: str) -> None:
        """ワーカーをキャンセルする。"""
        worker = self._active_workers.get(item_id)
        if worker:
            worker.cancel()
            # 結果通知とスレッド終了後の解放は別々に処理する

    @Slot(str, dict)
    def _on_worker_progress(self, item_id: str, data: dict) -> None:
        """ワーカーの進捗更新。"""
        item = self.find_item_by_id(item_id)
        if item is None or data.get('status') not in ('downloading', 'finished'):
            return
        item.record_transfer(data)
        total = data.get('total_bytes') or data.get('total_bytes_estimate')
        received = data.get('downloaded_bytes')
        if data.get('status') == 'finished':
            percent = 100.0
        elif isinstance(total, (int, float)) and total > 0 and isinstance(received, (int, float)):
            percent = received / total * 100
        else:
            try:
                percent = float(data.get('_percent_str', '0%').replace('%', '').strip())
            except (ValueError, AttributeError):
                percent = item.progress
        item.update_progress(percent)
        self.item_metadata_changed.emit(item_id)
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
        """結果を反映する。run() はまだ終了していないため解放しない。"""
        item = self.find_item_by_id(item_id)
        if item:
            if success:
                item.status = ItemStatus.COMPLETED
                item.progress = 100.0
                item.filepath = message
                try:
                    item.filesize_bytes = Path(message).stat().st_size
                    item.filesize = format_bytes(item.filesize_bytes)
                except OSError:
                    pass
                item.phase = ''
                self.item_metadata_changed.emit(item_id)
            else:
                if "キャンセル" in message:
                    item.status = ItemStatus.CANCELLED
                else:
                    item.status = ItemStatus.FAILED
                    item.error = message
            self.item_status_changed.emit(item_id, item.status.value)

        self.item_finished.emit(item_id, success, message)

    @Slot()
    def _cleanup_download_worker(self) -> None:
        """QThread.finished 後に解放し、空いた枠で次の処理を開始する。"""
        worker = self.sender()
        if not isinstance(worker, _SingleWorker):
            return
        if self._active_workers.get(worker.item_id) is worker:
            del self._active_workers[worker.item_id]
        worker.deleteLater()
        self._dispatch_next()
        self.queue_changed.emit()

    @Slot(list)
    def _on_playlist_expanded(self, urls: list) -> None:
        worker = self.sender()
        if self._closing or worker.generation != self._generation:
            return
        valid = []
        for url in urls:
            try:
                normalized, kind = classify_url(url)
                if kind == 'video':
                    valid.append(normalized)
            except ValueError:
                pass
        self.add_urls(valid)
        outcome = 'success' if valid else 'empty'
        message = f'{len(valid)} 件の動画を展開しました' if valid else '動画が見つかりませんでした'
        if not valid:
            self._expansion_errors[worker.playlist_url] = message
        self.expansion_result.emit(worker.operation_id, worker.playlist_url, outcome, message)

    @Slot(str)
    def _on_playlist_expand_failed(self, error: str) -> None:
        worker = self.sender()
        if self._closing or worker.generation != self._generation:
            return
        self._expansion_errors[worker.playlist_url] = error
        self.expansion_result.emit(worker.operation_id, worker.playlist_url, 'failed', error)


class _PlaylistExpandWorker(CancellableWorker):
    """プレイリストURLから個別の動画URLを抽出するワーカー。"""
    urls_extracted = Signal(list)
    expand_failed = Signal(str)

    def __init__(self, playlist_url: str, parent=None):
        super().__init__(parent)
        self.playlist_url = playlist_url
        self._downloader = Downloader(auto_update=False)

    def run(self):
        try:
            urls = self._downloader.extract_playlist_urls(self.playlist_url, self.is_cancelled)
            self.urls_extracted.emit(urls)
        except Exception as e:
            logger.error("Playlist extraction error: %s", e)
            self.expand_failed.emit(str(e))
