"""Offline regression checks for completion arriving before QThread exits."""
import sys
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QEvent
from shiboken6 import isValid

import queue_manager as qm
from downloader import DownloadRequest


class WorkerLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def pump_until(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.assertTrue(predicate())

    def test_completion_keeps_worker_alive_until_thread_exits(self):
        for success, message, status in (
            (True, '/tmp/result.mp4', qm.ItemStatus.COMPLETED),
            (False, 'download failed', qm.ItemStatus.FAILED),
            (False, 'キャンセルされました', qm.ItemStatus.CANCELLED),
        ):
            with self.subTest(status=status):
                release = Event()
                workers = []

                class HeldWorker(qm._SingleWorker):
                    def run(self):
                        self.finished_item.emit(self.item_id, success, message)
                        release.wait(5)

                manager = qm.BatchDownloadManager(max_concurrent=1)
                manager.items.extend([
                    qm.DownloadItem(url='https://example.com/first'),
                    qm.DownloadItem(url='https://example.com/second'),
                ])
                completed = []
                manager.all_finished.connect(lambda *args: completed.append(args))
                with patch.object(qm, '_SingleWorker', HeldWorker):
                    try:
                        manager.start_all(DownloadRequest(url='', output_path='/tmp'))
                        first = next(iter(manager._active_workers.values()))
                        workers.append(first)
                        self.pump_until(lambda: manager.items[0].status == status)
                        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                        self.assertTrue(isValid(first))
                        self.assertTrue(first.isRunning())
                        self.assertIn(first.item_id, manager._active_workers)
                        self.assertEqual(manager.items[1].status, qm.ItemStatus.PENDING)
                        self.assertEqual(completed, [])
                        release.set()
                        self.pump_until(lambda: bool(completed))
                        self.assertEqual(manager.items[1].status, status)
                        self.assertEqual(len(completed), 1)
                        self.assertFalse(manager._active_workers)
                        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                        self.assertFalse(isValid(first))
                    finally:
                        release.set()
                        workers.extend(manager._active_workers.values())
                        for worker in workers:
                            if isValid(worker):
                                worker.wait(3000)
                        self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
