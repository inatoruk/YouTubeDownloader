"""Cooperative cancellation shared by every background worker."""
from threading import Event
from PySide6.QtCore import QThread


class CancellableWorker(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_event = Event()

    def cancel(self):
        self._cancel_event.set()

    def is_cancelled(self):
        return self._cancel_event.is_set()
