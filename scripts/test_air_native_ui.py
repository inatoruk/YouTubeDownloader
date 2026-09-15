"""Offline regression coverage for Air × Native layout, intake and media data."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QScrollArea, QDialog
from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtNetwork import QNetworkReply
from qt_app import MainWindow
from queue_manager import DownloadItem, ItemStatus, BatchDownloadManager
from widgets.url_panel import UrlInputPanel
from widgets.queue_panel import QueuePanel
from widgets.progress_panel import ProgressPanel

APP = QApplication.instance() or QApplication([])
VIDEO = 'https://youtu.be/test'


class AirNativeTests(unittest.TestCase):
    def test_clipboard_is_fallback_and_enter_does_not_read_it(self):
        panel = UrlInputPanel()
        submitted, errors = [], []
        panel.url_submitted.connect(submitted.append)
        panel.status_message.connect(lambda msg, error: errors.append((msg, error)))
        clipboard = MagicMock()
        clipboard.text.return_value = 'https://youtu.be/copied'
        with patch('widgets.url_panel.QApplication.clipboard', return_value=clipboard):
            panel.url_input.setText(VIDEO)
            panel.add_btn.click()
            clipboard.text.assert_not_called()
            self.assertEqual(submitted, [VIDEO])
            panel._on_submit()
            clipboard.text.assert_not_called()
            panel.add_btn.click()
            self.assertEqual(submitted[-1], 'https://youtu.be/copied')
            self.assertEqual(panel.url_input.text(), '')
            clipboard.text.return_value = 'not a url'
            panel.add_btn.click()
            self.assertEqual(len(submitted), 2)
            self.assertEqual(panel.url_input.text(), 'not a url')
            self.assertTrue(errors[-1][1])
            panel.url_input.clear()
            clipboard.text.return_value = ''
            panel.add_btn.click()
            self.assertTrue(errors[-1][1])
        panel.shutdown()

    def test_multiline_clipboard_requires_bulk_confirmation(self):
        panel = UrlInputPanel()
        results = []
        panel.bulk_urls_submitted.connect(results.append)
        clipboard = MagicMock()
        clipboard.text.return_value = VIDEO+'\nhttps://youtu.be/second'
        with patch('widgets.url_panel.QApplication.clipboard', return_value=clipboard), patch('widgets.url_panel.BulkUrlDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.Rejected
            panel.add_btn.click()
            self.assertEqual(results, [])
            dialog.assert_called_with(panel, initial_urls=[VIDEO, 'https://youtu.be/second'])
            dialog.return_value.exec.return_value = QDialog.Accepted
            dialog.return_value.get_urls.return_value = [VIDEO]
            panel.add_btn.click()
            self.assertEqual(results, [[VIDEO]])
        panel.shutdown()

    def test_only_list_scrolls_at_both_window_sizes(self):
        window = MainWindow()
        self.assertEqual((window.width(), window.height()), (1200, 820))
        self.assertEqual(len(window.findChildren(QScrollArea)), 1)
        for width, height in ((800, 600), (960, 680), (1200, 820)):
            window.resize(width, height)
            window.show()
            APP.processEvents()
            fixed_positions = None
            for count in (0, 3, 100):
                items = [DownloadItem(VIDEO, title='長い動画タイトル ' * 30) for _ in range(count)]
                window._batch_manager._items = items
                window.queue_panel.rebuild(items)
                window._sync_ui_state()
                APP.processEvents()
                self.assertEqual((window.width(), window.height()), (width, height))
                positions = [(widget.mapTo(window, widget.rect().topLeft()).y(), widget.height())
                             for widget in (window.url_panel, window.progress_panel, window.download_btn)]
                if fixed_positions is None:
                    fixed_positions = positions
                self.assertEqual(positions, fixed_positions)
                if count == 100:
                    self.assertGreater(window.queue_panel.scroll.verticalScrollBar().maximum(), 0)
                    window.queue_panel.scroll.verticalScrollBar().setValue(1000)
                    APP.processEvents()
                    self.assertTrue(window.download_btn.isVisible())
                    self.assertTrue(window.progress_panel.isVisible())
                    row = next(iter(window.queue_panel._widgets.values()))
                    self.assertGreater(row.title_label.width(), 80)
        window.close()
        APP.processEvents()

    def test_transfer_counts_streams_once_and_caps_processing_progress(self):
        item = DownloadItem(VIDEO)
        formats = [{'format_id': 'v', 'filesize': 1000}, {'format_id': 'a', 'filesize': 200}]
        for received in (200, 400, 400, 300):
            item.record_transfer({'status': 'downloading', 'downloaded_bytes': received,
                                  'total_bytes': 1000, 'info_dict': {'format_id': 'v', 'requested_formats': formats}})
        self.assertEqual(item.downloaded_bytes, 400)
        self.assertEqual(item.transfer_total_bytes, 1200)
        item.record_transfer({'status': 'finished', 'downloaded_bytes': 1000, 'info_dict': {'format_id': 'v'}})
        item.record_transfer({'status': 'finished', 'downloaded_bytes': 200, 'info_dict': {'format_id': 'a'}})
        self.assertEqual(item.downloaded_bytes, 1200)
        self.assertEqual(item.transfer_total_bytes, 1200)
        item.update_progress(100)
        item.update_progress(0)
        item.update_progress(100)
        self.assertEqual(item.display_progress, 99)
        item.reset_for_retry()
        self.assertEqual(item.downloaded_bytes, 0)
        self.assertEqual(item.display_progress, 0)
        self.assertEqual(item.stream_totals, {})

    def test_unknown_total_and_completed_output_size(self):
        item = DownloadItem(VIDEO)
        panel = ProgressPanel()
        panel.update_capacity([item])
        self.assertEqual(panel.capacity_label.text(), '0 B / —')
        item.record_transfer({'status': 'downloading', 'downloaded_bytes': 250})
        panel.update_capacity([item])
        self.assertEqual(panel.capacity_label.text(), '250 B / —')
        manager = BatchDownloadManager()
        manager._items = [item]
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/'output.mp4'
            file.write_bytes(b'x'*512)
            manager._on_worker_finished(item.id, True, str(file))
        self.assertEqual(item.filesize_bytes, 512)
        self.assertEqual(item.display_progress, 100)
        manager.shutdown()

    def test_thumbnail_failure_and_removed_response_are_ignored(self):
        panel = QueuePanel()
        item = DownloadItem(VIDEO)
        panel.add_item(item.id, item)
        pixmap_before = panel._widgets[item.id].thumbnail.pixmap().cacheKey()
        reply = MagicMock()
        reply.error.return_value = QNetworkReply.ContentNotFoundError
        panel._active[reply] = (item.id, 'https://example.invalid/image.jpg')
        panel._finish_thumbnail(reply)
        self.assertEqual(panel._widgets[item.id].thumbnail.pixmap().cacheKey(), pixmap_before)
        panel.remove_widget(item.id)
        reply2 = MagicMock()
        reply2.error.return_value = QNetworkReply.NoError
        reply2.readAll.return_value = QByteArray(b'broken image')
        panel._active[reply2] = (item.id, 'https://example.invalid/image.jpg')
        panel._finish_thumbnail(reply2)
        reply2.readAll.assert_not_called()
        self.assertFalse(panel._active)
        panel.shutdown()

    def test_thumbnail_success_and_audio_layout_at_minimum_size(self):
        window = MainWindow()
        window.resize(800, 600)
        window.show()
        window.format_panel.audio_radio.setChecked(True)
        window.format_panel.format_combo.setCurrentText('WAV')
        APP.processEvents()
        self.assertTrue(window.format_panel._audio_container.isVisible())
        self.assertFalse(window.format_panel.bitrate_combo.isVisible())
        self.assertEqual((window.width(), window.height()), (800, 600))
        window.format_panel.format_combo.setCurrentText('MP3')
        APP.processEvents()
        self.assertTrue(window.format_panel.bitrate_combo.isVisible())
        item = DownloadItem(VIDEO)
        panel = window.queue_panel
        panel.add_item(item.id, item)
        widget = panel._widgets[item.id]
        widget._thumbnail_url = 'https://example.invalid/image.png'
        source = QPixmap(320, 180)
        source.fill(QColor('#3378E6'))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        source.save(buffer, 'PNG')
        buffer.close()
        reply = MagicMock()
        reply.error.return_value = QNetworkReply.NoError
        reply.readAll.return_value = data
        panel._active[reply] = (item.id, widget._thumbnail_url)
        panel._finish_thumbnail(reply)
        self.assertTrue(widget._has_thumbnail)
        self.assertEqual(widget.thumbnail.pixmap().toImage().pixelColor(0, 0).alpha(), 0)
        self.assertGreater(widget.thumbnail.pixmap().toImage().pixelColor(86, 54).alpha(), 0)
        self.assertEqual(widget.thumbnail.pixmap().deviceIndependentSize().width(), 86)
        self.assertIn(widget._thumbnail_url, panel._cache)
        window.close()
        APP.processEvents()

    def test_segment_animation_retargets_and_preserves_selection(self):
        window = MainWindow()
        window.show()
        APP.processEvents()
        panel = window.format_panel
        panel.audio_radio.click()
        APP.processEvents()
        self.assertEqual(panel.get_format_type(), 'audio')
        animation = panel.segment._animation
        animation.setCurrentTime(100)
        self.assertFalse(panel.segment.grab().isNull())
        panel.video_radio.click()
        APP.processEvents()
        animation.setCurrentTime(animation.duration())
        self.assertEqual(panel.get_format_type(), 'video')
        self.assertEqual(panel.segment._selection, panel.segment._target())
        window.close()
        APP.processEvents()

    def test_segment_edges_lead_then_catch_up_inside_track(self):
        window = MainWindow()
        window.show()
        APP.processEvents()
        panel = window.format_panel
        segment = panel.segment
        animation = segment._animation
        for button, rightward in ((panel.audio_radio, True), (panel.video_radio, False)):
            start = segment._target()
            button.click()
            animation.setCurrentTime(20)
            rect = segment._selection
            if rightward:
                self.assertEqual(rect.left(), start.left())
                self.assertGreater(rect.right(), start.right())
            else:
                self.assertEqual(rect.right(), start.right())
                self.assertLess(rect.left(), start.left())
            for time in range(20, animation.duration() + 1, 4):
                animation.setCurrentTime(time)
                rect = segment._selection
                self.assertGreaterEqual(rect.left(), 3)
                self.assertLessEqual(rect.right(), segment.width() - 3)
                self.assertEqual(rect.height(), start.height())
                self.assertGreater(rect.width(), 0)
            self.assertEqual(segment._selection, segment._target())
        panel.audio_radio.click()
        animation.setCurrentTime(130)
        before = segment._selection
        panel.video_radio.click()
        self.assertEqual(segment._selection, before)
        animation.setCurrentTime(animation.duration())
        self.assertEqual(segment._selection, segment._target())
        window.close()
        APP.processEvents()

    def test_scheme_updates_existing_rows_and_draws(self):
        window = MainWindow()
        items = [DownloadItem(VIDEO, title=title, uploader='Studio journal', duration='12:48', filesize='186 MB')
                 for title in ('A quiet morning in Kyoto', 'Designing a calmer workspace', 'Ambient piano — slow afternoon')]
        window._batch_manager._items = items
        window.queue_panel.rebuild(items)
        window._sync_ui_state()
        window.show()
        APP.processEvents()
        for scheme in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
            window._on_color_scheme(scheme)
            APP.processEvents()
            shot = window.grab()
            self.assertFalse(shot.isNull())
            if os.environ.get('YD_UI_CAPTURE_DIR'):
                shot.save(str(Path(os.environ['YD_UI_CAPTURE_DIR']) / f'air-native-{scheme.name}.png'))
        window.close()
        APP.processEvents()


if __name__ == '__main__':
    unittest.main()
