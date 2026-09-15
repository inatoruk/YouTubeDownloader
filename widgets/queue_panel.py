"""Scrollable media list and bounded asynchronous thumbnail loading."""
from collections import OrderedDict
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QSizePolicy, QMenu, QStyle, QLayout,
)
from PySide6.QtCore import Qt, Signal, QUrl, QSize, QTimer
from PySide6.QtGui import QPainter, QPixmap, QColor, QPainterPath
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from theme import Theme, STATUS_ICONS
from queue_manager import ItemStatus, format_bytes
from widgets.smooth_progress import SmoothProgressBar


class ElidedLabel(QLabel):
    """Keep full accessible text without letting long titles expand the window."""
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setToolTip(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().height() + 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.contentsRect(), Qt.AlignVCenter | Qt.AlignLeft,
                         self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.contentsRect().width()))


class QueueItemWidget(QFrame):
    remove_clicked = Signal(str)
    retry_clicked = Signal(str)

    def __init__(self, item_id, item, parent=None):
        super().__init__(parent)
        self.item_id, self._url = item_id, item.url
        self._item = item
        self._thumbnail_url = ''
        self.setObjectName('QueueItem')
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(84)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 15, 6, 15)
        layout.setSpacing(12)
        thumbnail_box = QWidget()
        thumbnail_box.setFixedSize(86, 54)
        self.thumbnail = QLabel(thumbnail_box)
        self.thumbnail.setObjectName('Thumbnail')
        self.thumbnail.setGeometry(0, 0, 86, 54)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        self._has_thumbnail = False
        self.duration_label = QLabel(item.duration or '', thumbnail_box)
        self.duration_label.setObjectName('Duration')
        self.duration_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(thumbnail_box)
        info = QVBoxLayout()
        info.setSpacing(3)
        self.title_label = ElidedLabel(item.title or item.url)
        self.title_label.setObjectName("MediaTitle")
        self.url_label = ElidedLabel(item.uploader or item.url)
        self.url_label.setObjectName('Secondary')
        self.size_label = QLabel(item.filesize or '—')
        self.size_label.setObjectName('Secondary')
        info.addWidget(self.title_label)
        info.addWidget(self.url_label)
        info.addWidget(self.size_label)
        self.progress_bar = SmoothProgressBar()
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setRadius(2)
        info.addWidget(self.progress_bar)
        layout.addLayout(info, 1)
        self.status_icon = QLabel()
        self.status_icon.setObjectName('Secondary')
        self.status_icon.setMinimumWidth(45)
        self.status_icon.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.status_icon)
        self.retry_btn = QPushButton('↻')
        self.remove_btn = QPushButton('×')
        for button, title, signal in ((self.retry_btn, '再試行', self.retry_clicked),
                                      (self.remove_btn, '削除', self.remove_clicked)):
            button.setObjectName('icon')
            button.setFixedSize(26, 28)
            button.setToolTip(title)
            button.setAccessibleName(title)
            button.clicked.connect(lambda checked=False, sig=signal: sig.emit(self.item_id))
            layout.addWidget(button)
        self.update_duration(item.duration or '')
        self.update_status(item.status)
        self.update_progress(item.display_progress)

    @staticmethod
    def _shorten_url(url):
        return url

    def update_status(self, status):
        self._status = status
        self.status_icon.setText(STATUS_ICONS[status])
        self.retry_btn.setVisible(status in (ItemStatus.FAILED, ItemStatus.CANCELLED))
        self.remove_btn.setVisible(status != ItemStatus.DOWNLOADING)
        self.progress_bar.setVisible(status == ItemStatus.DOWNLOADING)
        self.refresh_theme()
        if status == ItemStatus.COMPLETED:
            self.progress_bar.setProgressImmediate(1)
        elif status in (ItemStatus.PENDING, ItemStatus.RESOLVING, ItemStatus.DOWNLOADING):
            self.url_label.setText(self._item.uploader or self._url)
            self.url_label.setObjectName('Secondary')
            self.setToolTip('')
            if status == ItemStatus.PENDING:
                self.progress_bar.setProgressImmediate(0)
        self.url_label.style().unpolish(self.url_label)
        self.url_label.style().polish(self.url_label)

    def refresh_theme(self):
        if not self._has_thumbnail:
            icon = self.style().standardIcon(QStyle.SP_MediaPlay).pixmap(24, 24)
            painter = QPainter(icon)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(icon.rect(), QColor(Theme.TEXT_TERTIARY))
            painter.end()
            self.thumbnail.setPixmap(icon)
        self.progress_bar.setColors(Theme.ACCENT)
        color = Theme.ERROR if self._status == ItemStatus.FAILED else Theme.SUCCESS if self._status == ItemStatus.COMPLETED else Theme.TEXT_SECONDARY
        self.status_icon.setStyleSheet(f'color: {color}; font-size: 14px;')

    def update_progress(self, percent):
        self.progress_bar.setProgress(percent / 100)
        if self._status == ItemStatus.DOWNLOADING:
            self.status_icon.setText('変換中' if self._item.phase == '変換・結合中' else f'{int(percent)}%')

    def set_error(self, message):
        if message:
            self.url_label.setText(message)
            self.url_label.setObjectName('Error')
            self.url_label.style().unpolish(self.url_label)
            self.url_label.style().polish(self.url_label)
            self.setToolTip(message)

    def update_title(self, title):
        self.title_label.setText(title)

    def update_duration(self, duration):
        self.duration_label.setText(duration)
        self.duration_label.adjustSize()
        self.duration_label.move(82 - self.duration_label.width(), 50 - self.duration_label.height())
        self.duration_label.setVisible(bool(duration))

    def update_filesize(self, filesize):
        self.size_label.setText(filesize or '—')

    def set_thumbnail(self, pixmap):
        if not pixmap.isNull():
            self._has_thumbnail = True
            scaled = pixmap.scaled(172, 108, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            cropped = scaled.copy((scaled.width()-172)//2, (scaled.height()-108)//2, 172, 108)
            rounded = QPixmap(172, 108)
            rounded.fill(Qt.transparent)
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.Antialiasing)
            clip = QPainterPath()
            clip.addRoundedRect(0, 0, 172, 108, 14, 14)
            painter.setClipPath(clip)
            painter.drawPixmap(0, 0, cropped)
            painter.end()
            rounded.setDevicePixelRatio(2)
            self.thumbnail.setPixmap(rounded)


class QueuePanel(QFrame):
    remove_item = Signal(str)
    retry_item = Signal(str)
    retry_all_failed = Signal()
    clear_completed = Signal()
    clear_all = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Card')
        self._widgets = {}
        self._network = QNetworkAccessManager(self)
        self._pending = {}
        self._active = {}
        self._cache = OrderedDict()
        self._closed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel('ダウンロード一覧')
        title.setObjectName('Title')
        self.count_label = QLabel('0 件')
        self.count_label.setObjectName('Secondary')
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.count_label)
        self.menu_btn = QPushButton('···')
        self.menu_btn.setObjectName('icon')
        self.menu_btn.setFixedSize(28, 28)
        self.menu_btn.setAccessibleName('一覧の管理')
        menu = QMenu(self)
        self.retry_all_btn = menu.addAction('失敗を再試行', self.retry_all_failed.emit)
        self.clear_btn = menu.addAction('完了をクリア', self.clear_completed.emit)
        self.clear_all_btn = menu.addAction('すべてクリア', self.clear_all.emit)
        self.menu_btn.setMenu(menu)
        header.addWidget(self.menu_btn)
        layout.addLayout(header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(80)
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_widget)
        layout.addWidget(self.scroll, 1)
        self.empty_label = QLabel('URLを追加してください', self.scroll.viewport())
        self.empty_label.setObjectName('Secondary')
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.scroll.viewport().installEventFilter(self)
        self.update_counts(0, 0, 0, False)

    def eventFilter(self, obj, event):
        if obj is self.scroll.viewport():
            self.empty_label.setGeometry(self.scroll.viewport().rect())
        return super().eventFilter(obj, event)

    def add_item(self, item_id, item):
        widget = QueueItemWidget(item_id, item)
        widget.remove_clicked.connect(self.remove_item.emit)
        widget.retry_clicked.connect(self.retry_item.emit)
        self._widgets[item_id] = widget
        self.list_layout.insertWidget(self.list_layout.count()-1, widget)
        self.update_metadata(item)

    def remove_widget(self, item_id):
        self._pending.pop(item_id, None)
        for reply, (key, url) in list(self._active.items()):
            if key == item_id:
                reply.abort()
        widget = self._widgets.pop(item_id, None)
        if widget:
            widget.setParent(None)
            widget.deleteLater()

    def update_item_progress(self, item_id, percent):
        if item_id in self._widgets:
            self._widgets[item_id].update_progress(percent)

    def update_item_status(self, item_id, status):
        if item_id in self._widgets:
            self._widgets[item_id].update_status(status)

    def set_item_error(self, item_id, message):
        if item_id in self._widgets:
            self._widgets[item_id].set_error(message)

    def update_item_title(self, item_id, title):
        if item_id in self._widgets:
            self._widgets[item_id].update_title(title)

    def update_item_duration(self, item_id, duration):
        if item_id in self._widgets:
            self._widgets[item_id].update_duration(duration)

    def update_item_filesize(self, item_id, filesize):
        if item_id in self._widgets:
            self._widgets[item_id].update_filesize(filesize)

    def update_metadata(self, item):
        widget = self._widgets.get(item.id)
        if not widget:
            return
        widget.update_duration(item.duration or '')
        if not item.error:
            widget.url_label.setText(item.uploader or item.url)
        size = format_bytes(item.filesize_bytes) if item.filesize_bytes is not None else item.filesize or '—'
        if item.status == ItemStatus.DOWNLOADING:
            size = f'{format_bytes(item.downloaded_bytes)} / {format_bytes(item.transfer_total_bytes)}'
        widget.update_filesize(size)
        if item.thumbnail_url and item.thumbnail_url != widget._thumbnail_url:
            widget._thumbnail_url = item.thumbnail_url
            if item.thumbnail_url in self._cache:
                widget.set_thumbnail(self._cache[item.thumbnail_url])
            else:
                self._pending[item.id] = item.thumbnail_url
                self._pump_thumbnails()

    def _pump_thumbnails(self):
        while self._pending and len(self._active) < 4 and not self._closed:
            item_id = next(iter(self._pending))
            url = self._pending.pop(item_id)
            if item_id not in self._widgets or QUrl(url).scheme() not in ('http', 'https'):
                continue
            request = QNetworkRequest(QUrl(url))
            request.setTransferTimeout(10000)
            reply = self._network.get(request)
            self._active[reply] = (item_id, url)
            reply.downloadProgress.connect(lambda received, total, r=reply: r.abort() if max(received, total) > 5*1024*1024 else None)
            reply.finished.connect(lambda r=reply: self._finish_thumbnail(r))

    def _finish_thumbnail(self, reply):
        identity = self._active.pop(reply, None)
        if identity and not self._closed:
            item_id, url = identity
            widget = self._widgets.get(item_id)
            if widget and widget._thumbnail_url == url and reply.error() == QNetworkReply.NoError:
                pixmap = QPixmap()
                if pixmap.loadFromData(reply.readAll()):
                    pixmap = pixmap.scaled(172, 108, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    self._cache[url] = pixmap
                    while len(self._cache) > 128:
                        self._cache.popitem(last=False)
                    widget.set_thumbnail(pixmap)
        reply.deleteLater()
        QTimer.singleShot(0, self._pump_thumbnails)

    def shutdown(self):
        self._closed = True
        self._pending.clear()
        for reply in list(self._active):
            reply.abort()

    def rebuild(self, items):
        for item_id in list(self._widgets):
            self.remove_widget(item_id)
        for item in items:
            self.add_item(item.id, item)
            if item.error:
                self.set_item_error(item.id, item.error)

    def refresh_theme(self):
        for widget in self._widgets.values():
            widget.refresh_theme()

    def update_counts(self, total, completed, failed, is_running):
        self.empty_label.setVisible(not self._widgets)
        self.count_label.setText(f'{total} 件' + (f' · 完了 {completed}' if completed else '') + (f' · 失敗 {failed}' if failed else ''))
        self.retry_all_btn.setEnabled(failed > 0 and not is_running)
        self.clear_btn.setEnabled((completed > 0 or failed > 0) and not is_running)
        self.clear_all_btn.setEnabled(total > 0 and not is_running)
