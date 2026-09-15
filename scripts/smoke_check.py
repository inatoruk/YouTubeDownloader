"""Offline GUI path smoke checks; does not contact YouTube or change user logs."""
import os
import sys
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from PySide6.QtWidgets import QApplication
from qt_app import MainWindow
from widgets.url_panel import _ChannelFetchWorker
from downloader import Downloader

def main():
    app=QApplication.instance() or QApplication([])
    window=MainWindow()
    manager=window._batch_manager
    with patch.object(manager,'add_urls') as add, patch.object(manager,'add_playlist_items') as playlist:
        window._on_url_submitted('https://youtu.be/test')
        add.assert_called_once_with(['https://youtu.be/test'])
        add.reset_mock()
        window._on_bulk_urls_submitted(['https://youtu.be/test','https://www.youtube.com/playlist?list=TEST'])
        add.assert_called_once_with(['https://youtu.be/test'])
        playlist.assert_called_once()
        add.reset_mock()
        window.url_panel.url_input.setText('https://youtu.be/test')
        window._on_start_batch()
        add.assert_called_once_with(['https://youtu.be/test'])
        assert not window.url_panel.url_input.text()
    result=[]
    worker=_ChannelFetchWorker('https://www.youtube.com/@test')
    worker.urls_fetched.connect(result.append)
    with patch.object(Downloader,'extract_channel_urls',return_value=['https://youtu.be/test']):
        worker.run()
    assert result==[['https://youtu.be/test']]
    with patch('qt_app.QMessageBox.exec', return_value=0):
        window._on_stop_all()
    window.close()
    app.processEvents()
    print('PASS: GUI construction; single/bulk/direct/channel import paths; stop. Network stubbed.')

if __name__=='__main__':main()
