"""Offline publication, postprocessor-path and cancellation regressions."""
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from downloader import Downloader, DownloadRequest, DownloadError, DownloadCancelled
from utils.urls import classify_url


class SafetyTests(unittest.TestCase):
    def test_parallel_publication_preserves_every_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'same.mp4').write_text('original')
            barrier = Barrier(4)
            def fake_download(downloader, request, *args):
                result = Path(request.output_path) / 'same.mp4'
                result.write_text(request.url)
                barrier.wait(5)
                return str(result)
            def download(index):
                return Downloader(auto_update=False).download(DownloadRequest(str(index), folder))
            with patch.object(Downloader, '_download_to_directory', fake_download), ThreadPoolExecutor(4) as pool:
                results = list(pool.map(download, range(4)))
            self.assertEqual(len(set(results)), 4)
            self.assertEqual((root / 'same.mp4').read_text(), 'original')
            self.assertEqual({Path(p).read_text() for p in results}, {'0', '1', '2', '3'})
            self.assertEqual(len(list(root.iterdir())), 5)

    def test_failed_publication_removes_only_own_reservation(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / 'same.mp4'
            original.write_text('original')
            def fake_download(request, *args):
                result = Path(request.output_path) / 'same.mp4'
                result.write_text('new')
                return str(result)
            downloader = Downloader(auto_update=False)
            with patch.object(downloader, '_download_to_directory', fake_download), patch('downloader.os.replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    downloader.download(DownloadRequest('test', folder))
            self.assertEqual(list(Path(folder).iterdir()), [original])
            self.assertEqual(original.read_text(), 'original')

    def test_postprocessed_path_and_invalid_final_extension(self):
        for extension in ('mp4', 'webm'):
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as folder:
                class FakeYDL:
                    def __init__(self, options):
                        self.root = Path(options['outtmpl']).parent
                        self.options = options
                    def __enter__(self): return self
                    def __exit__(self, *args): return False
                    def extract_info(self, *args, **kwargs):
                        result = self.root / f'remuxed.{extension}'
                        result.write_bytes(b'video')
                        return {'ext': 'webm', 'requested_downloads': [{'filepath': str(result)}]}
                downloader = Downloader(max_retries=1, auto_update=False)
                self.assertEqual(downloader._build_options(DownloadRequest('', folder), [])['postprocessors'][0]['key'], 'FFmpegVideoRemuxer')
                with patch('downloader.yt_dlp.YoutubeDL', FakeYDL):
                    if extension == 'mp4':
                        result = downloader.download(DownloadRequest('test', folder))
                        self.assertEqual(Path(result).name, 'remuxed.mp4')
                    else:
                        with self.assertRaises(DownloadError):
                            downloader.download(DownloadRequest('test', folder))
                        self.assertEqual(list(Path(folder).iterdir()), [])

    def test_cancelled_extraction_never_starts_network(self):
        with patch('downloader.yt_dlp.YoutubeDL') as ydl:
            with self.assertRaises(DownloadCancelled):
                Downloader(auto_update=False)._extract('x', {}, lambda info: info, lambda: True)
            ydl.assert_not_called()


class UrlTests(unittest.TestCase):
    def test_classification_and_normalization(self):
        examples = {
            'youtu.be/test': ('https://youtu.be/test', 'video'),
            'https://m.youtube.com/watch?v=x&list=PL1': ('https://m.youtube.com/watch?v=x&list=PL1', 'playlist'),
            'https://music.youtube.com/watch?v=x': ('https://music.youtube.com/watch?v=x', 'video'),
            'https://youtube.com/@%E6%97%A5%E6%9C%AC/videos': ('https://youtube.com/@%E6%97%A5%E6%9C%AC/videos', 'channel'),
            'https://youtu.be/x?token=a%26b': ('https://youtu.be/x?token=a%26b', 'video'),
        }
        for url, expected in examples.items():
            self.assertEqual(classify_url(url), expected)

    def test_external_and_malformed_urls_rejected(self):
        for url in ('https://example.com/?list=PL1', 'https://youtube.com.evil/playlist?list=PL1',
                    'https://evil/youtube.com/playlist?list=PL1', 'file://youtube.com/watch?v=x',
                    'https://user@youtube.com/watch?v=x', 'https://youtube.com/playlist', '',
                    'https://youtube.com/watch', 'https://youtube.com:bad/watch?v=x'):
            with self.subTest(url=url), self.assertRaises(ValueError): classify_url(url)


if __name__ == '__main__': unittest.main()
