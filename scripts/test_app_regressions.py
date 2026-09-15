"""Offline Qt integration tests. Requires a working Qt platform plugin."""
import os
import sys
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialog
from downloader import Downloader, DownloadRequest
from queue_manager import BatchDownloadManager, DownloadItem, ItemStatus
from qt_app import MainWindow, _YtDlpUpdateWorker
from widgets.queue_panel import QueueItemWidget
from widgets.smooth_progress import SmoothProgressBar
from widgets.url_panel import BulkUrlDialog

VIDEO = 'https://youtu.be/test'
PLAYLIST = 'https://youtube.com/playlist?list=PLtest'
CHANNEL = 'https://youtube.com/@test'


class AppRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def pump(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertTrue(predicate())

    def test_progress_retry_and_rebuild(self):
        item = DownloadItem(VIDEO)
        item.update_progress(100)
        item.update_progress(50)
        self.assertEqual(item.display_progress, 95)
        self.assertEqual(item.display_progress, 95)
        item.status = ItemStatus.FAILED
        item.error = 'network failure'
        item.filepath = 'old-path'
        manager = BatchDownloadManager()
        manager.items.append(item)
        window = MainWindow()
        window.queue_panel.rebuild(manager.items)
        widget = window.queue_panel._widgets[item.id]
        self.assertEqual(widget.url_label.text(), 'network failure')
        manager.item_status_changed.connect(lambda item_id, status: widget.update_status(ItemStatus(status)))
        manager.item_progress.connect(lambda item_id, percent: widget.update_progress(percent))
        manager.retry_all_failed()
        self.assertEqual(item.display_progress, 0)
        self.assertIsNone(item.filepath)
        self.assertIsNone(item.error)
        self.assertEqual(widget.url_label.text(), VIDEO)
        self.assertEqual(widget.toolTip(), '')
        item.update_progress(10)
        self.assertEqual(item.display_progress, 9)
        window.close()

    def test_progress_timer_stops_at_partial_target(self):
        bar = SmoothProgressBar()
        bar.setProgress(.4)
        for _ in range(250): bar._update_frame()
        self.assertFalse(bar.anim_timer.isActive())
        self.assertEqual(bar._current_progress, .4)
        bar.setProgress(.5)
        self.assertTrue(bar.anim_timer.isActive())
        bar.setProgressImmediate(0)
        self.assertFalse(bar.anim_timer.isActive())

    def test_all_intake_routes_validate_and_direct_start_expands(self):
        window = MainWindow()
        manager = window._batch_manager
        with patch.object(manager, 'add_urls') as add, patch.object(manager, 'add_playlist_items') as expand, patch.object(window.url_panel, 'request_channel') as channel:
            window._on_url_submitted('youtu.be/test')
            add.assert_called_once_with([VIDEO])
            add.reset_mock()
            window._on_bulk_urls_submitted([VIDEO, PLAYLIST, 'https://evil/?list=PL1', CHANNEL])
            add.assert_called_once_with([VIDEO])
            expand.assert_called_once_with(PLAYLIST)
            channel.assert_called_once_with(CHANNEL, False)
            add.reset_mock(); expand.reset_mock()
            window.url_panel.url_input.setText(PLAYLIST)
            window._on_start_batch()
            expand.assert_called_once_with(PLAYLIST)
            add.assert_not_called()
            window._intake_urls(['https://evil/?list=PL1'], True)
            add.assert_not_called()
        window.close()

    def test_playlist_completion_waits_and_empty_is_failure(self):
        for urls, expected in (([VIDEO], (1, 0)), ([], (0, 1))):
            manager = BatchDownloadManager()
            release = Event()
            results = []
            manager.all_finished.connect(lambda *result: results.append(result))
            def expand(*args):
                release.wait(5)
                return urls
            with patch.object(Downloader, 'extract_playlist_urls', expand), patch.object(Downloader, 'fetch_info', return_value={'title': 'Test'}), patch.object(Downloader, 'download', return_value='/tmp/test.mp4'):
                try:
                    manager.add_playlist_items(PLAYLIST)
                    manager.start_all(DownloadRequest('', '/tmp'))
                    self.assertTrue(manager.is_running)
                    self.assertEqual(results, [])
                    release.set()
                    self.pump(lambda: bool(results) and not manager.busy)
                    self.assertEqual(results, [expected])
                finally:
                    release.set()
                    manager.shutdown()
                    self.pump(lambda: not manager.busy)

    def test_clear_discards_delayed_expansion(self):
        manager = BatchDownloadManager()
        release = Event()
        started = Event()
        def expand(*args):
            started.set(); release.wait(5)
            return [VIDEO]
        with patch.object(Downloader, 'extract_playlist_urls', expand), patch.object(Downloader, 'fetch_info') as fetch:
            try:
                manager.add_playlist_items(PLAYLIST)
                self.pump(started.is_set)
                manager.clear_all()
                release.set()
                self.pump(lambda: not manager.busy)
                self.assertEqual(manager.total_count, 0)
                fetch.assert_not_called()
            finally:
                release.set()
                manager.shutdown()
                self.pump(lambda: not manager.busy)

    def test_expansion_error_is_visible_and_counted(self):
        window = MainWindow()
        manager = window._batch_manager
        results = []
        manager.all_finished.connect(lambda *result: results.append(result))
        with patch.object(Downloader, 'extract_playlist_urls', side_effect=RuntimeError('offline')), patch('qt_app.QMessageBox.exec', return_value=0):
            window._intake_urls([PLAYLIST], True)
            self.pump(lambda: bool(results) and not manager.busy)
            self.assertEqual(results, [(0, 1)])
            self.assertIn('offline', window.progress_panel.status_label.text())
        window.close()

    def test_stop_waits_for_download_and_keeps_pending(self):
        window = MainWindow()
        manager = window._batch_manager
        release = Event()
        manager.items.extend([DownloadItem(VIDEO), DownloadItem('https://youtu.be/second'), DownloadItem('https://youtu.be/third')])
        def download(*args, **kwargs):
            release.wait(5)
            return '/tmp/test.mp4'
        with patch.object(Downloader, 'download', download):
            try:
                window._start_batch_download()
                window._on_stop_all()
                self.assertTrue(window._stopping)
                self.assertFalse(window.download_btn.isEnabled())
                self.assertIn('停止処理中', window.progress_panel.status_label.text())
                release.set()
                self.pump(lambda: not manager.busy)
                self.assertFalse(window._stopping)
                self.assertEqual(manager.items[-1].status, ItemStatus.PENDING)
                self.assertFalse(manager.is_running)
            finally:
                release.set(); window.close(); self.pump(lambda: not manager.busy)

    def test_close_waits_for_all_worker_types_without_late_dialogs(self):
        window = MainWindow()
        window.show()
        manager = window._batch_manager
        release = Event()
        def held(value):
            def call(*args, **kwargs):
                release.wait(5)
                return value
            return call
        with patch.object(Downloader, 'download', held('/tmp/test.mp4')), patch.object(Downloader, 'fetch_info', held({'title': 'test'})), patch.object(Downloader, 'extract_playlist_urls', held([VIDEO])), patch.object(Downloader, 'extract_channel_urls', held([VIDEO])), patch.object(Downloader, '_ensure_updated', held(None)), patch('qt_app.QMessageBox.exec') as message, patch.object(BulkUrlDialog, 'exec') as dialog:
            try:
                manager.items.append(DownloadItem('https://youtu.be/active'))
                window._start_batch_download()
                manager.add_urls([VIDEO])
                manager.add_playlist_items(PLAYLIST)
                window.url_panel.request_channel(CHANNEL)
                window._update_worker = _YtDlpUpdateWorker(window)
                window._update_worker.start()
                window.close()
                self.assertTrue(window.isVisible())
                self.assertTrue(window._closing)
                release.set()
                self.pump(lambda: not window.isVisible())
                self.assertFalse(manager.busy)
                self.assertFalse(window.url_panel.busy)
                self.assertFalse(window._update_worker.isRunning())
                message.assert_not_called()
                dialog.assert_not_called()
            finally:
                release.set(); window.close()
                self.pump(lambda: not manager.busy and not window.url_panel.busy and not window._update_worker.isRunning())

    def test_channel_confirmation_revalidates_edits_and_stale_results_are_ignored(self):
        window = MainWindow()
        manager = window._batch_manager
        with patch.object(Downloader, 'extract_channel_urls', return_value=[VIDEO]), patch.object(BulkUrlDialog, 'exec', return_value=QDialog.Accepted), patch.object(BulkUrlDialog, 'get_urls', return_value=[VIDEO, 'https://evil/?list=PL1']), patch.object(manager, 'add_urls') as add:
            window.url_panel.request_channel(CHANNEL)
            self.pump(lambda: not window.url_panel.busy)
            add.assert_called_once_with([VIDEO])
            self.assertIn('無効なURL', window.progress_panel.status_label.text())
        release = Event()
        started = Event()
        def held(*args):
            started.set(); release.wait(5)
            return [VIDEO]
        with patch.object(Downloader, 'extract_channel_urls', held), patch.object(BulkUrlDialog, 'exec') as dialog:
            try:
                window.url_panel.request_channel(CHANNEL, True)
                self.pump(started.is_set)
                self.assertTrue(window.queue_panel.clear_all_btn.isEnabled())
                window.url_panel.invalidate()
                release.set()
                self.pump(lambda: not window.url_panel.busy)
                dialog.assert_not_called()
                self.assertFalse(manager.is_running)
            finally:
                release.set(); window.close(); self.pump(lambda: not window.url_panel.busy)

    def test_stop_during_expansion_does_not_auto_start_download(self):
        window = MainWindow()
        manager = window._batch_manager
        release = Event()
        def held(*args):
            release.wait(5)
            return [VIDEO]
        with patch.object(Downloader, 'extract_playlist_urls', held), patch.object(Downloader, 'fetch_info', return_value={'title': 'test'}), patch.object(Downloader, 'download') as download:
            try:
                window._intake_urls([PLAYLIST], True)
                self.assertTrue(manager.is_running)
                self.assertFalse(window.format_panel.isEnabled())
                self.assertFalse(window.output_card.isEnabled())
                window._on_stop_all()
                release.set()
                self.pump(lambda: not manager.busy)
                download.assert_not_called()
                self.assertEqual(manager.pending_count, 1)
                self.assertFalse(manager.is_running)
            finally:
                release.set(); window.close(); self.pump(lambda: not manager.busy)

    def test_saved_directory_is_batch_snapshot(self):
        window = MainWindow()
        window._batch_manager._base_request = DownloadRequest('', '/tmp/actual')
        window.output_edit.setText('/tmp/next')
        with patch('qt_app.QMessageBox.exec', return_value=0), patch('qt_app.QMessageBox.clickedButton', return_value=None), patch('qt_app.QMessageBox.addButton', return_value=None), patch('qt_app.QDesktopServices.openUrl') as open_url:
            window._on_all_finished(1, 0)
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), '/tmp/actual')
        window.close()


if __name__ == '__main__': unittest.main()
