"""Fixed aggregate progress and capacity footer."""
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QFrame
from theme import Theme
from widgets.smooth_progress import SmoothProgressBar
from widgets.queue_panel import ElidedLabel
from queue_manager import format_bytes


class ProgressPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Card')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        top = QHBoxLayout()
        title = QLabel('全体進捗')
        title.setObjectName('Title')
        self.value_label = QLabel('0%')
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.value_label)
        layout.addLayout(top)
        self.progress_bar = SmoothProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRadius(3)
        layout.addWidget(self.progress_bar)
        details = QHBoxLayout()
        self.percent_label = QLabel('0/0 完了')
        self.capacity_label = QLabel('0 B / —')
        for label in (self.percent_label, self.capacity_label):
            label.setObjectName('Secondary')
        details.addWidget(self.percent_label)
        details.addStretch()
        details.addWidget(self.capacity_label)
        layout.addLayout(details)
        self.status_label = ElidedLabel('待機中')
        self.status_label.setObjectName('Secondary')
        layout.addWidget(self.status_label)
        self.refresh_theme()

    def refresh_theme(self):
        self.progress_bar.setColors(Theme.ACCENT)
        self.value_label.setStyleSheet(f'color: {Theme.ACCENT}; font-size: 15px;')

    def set_status(self, msg, is_error=False):
        self.status_label.setText(msg)
        self.status_label.setObjectName('Error' if is_error else 'Secondary')
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def update_progress(self, percent, completed, total):
        percent = max(0, min(100, percent))
        if completed == total and total > 0 and percent == 100:
            self.progress_bar.setProgressImmediate(1)
        else:
            self.progress_bar.setProgress(percent / 100)
        self.value_label.setText(f'{int(percent)}%')
        self.percent_label.setText(f'{completed}/{total} 完了')

    def update_capacity(self, items):
        received = sum(item.downloaded_bytes for item in items)
        totals = [item.transfer_total_bytes for item in items]
        total = sum(totals) if totals and all(n is not None for n in totals) else None
        self.capacity_label.setText(f'{format_bytes(received)} / {format_bytes(total)}')

    def reset(self):
        self.progress_bar.reset()
        self.value_label.setText('0%')
        self.percent_label.setText('0/0 完了')
        self.capacity_label.setText('0 B / —')
