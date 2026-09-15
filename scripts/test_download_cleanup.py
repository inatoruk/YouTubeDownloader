"""Offline checks for isolated download cleanup and final-file publication."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from downloader import DownloadCancelled, DownloadError, DownloadRequest, Downloader


class DownloadCleanupTest(unittest.TestCase):
    def test_cleanup_and_preservation(self):
        for outcome in ('cancel', 'wrapped_cancel', 'late_cancel', 'failure', 'success'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                existing = root / 'video.mp4'
                existing.write_bytes(b'existing')
                other = root / '.youtube-download-other'
                other.mkdir()
                (other / 'other.part').write_bytes(b'other')
                cancelled = [False]
                work_dirs = []

                class FakeYDL:
                    def __init__(self, options):
                        self.folder = Path(options['outtmpl']).parent
                        work_dirs.append(self.folder)
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        return False
                    def extract_info(self, *args, **kwargs):
                        for name in ('video.part', 'video.ytdl', 'video.f137.mp4', 'video.part-Frag1'):
                            (self.folder / name).write_bytes(b'partial')
                        if outcome in ('cancel', 'wrapped_cancel'):
                            cancelled[0] = True
                            if outcome == 'cancel':
                                raise DownloadCancelled('cancelled')
                            raise RuntimeError('wrapped cancellation')
                        if outcome == 'failure':
                            raise RuntimeError('video unavailable')
                        (self.folder / 'video.mp4').write_bytes(b'complete')
                        cancelled[0] = outcome == 'late_cancel'
                        return {'title': 'video', 'requested_downloads': [{'filepath': str(self.folder / 'video.mp4')}]}
                    def prepare_filename(self, info):
                        return str(self.folder / 'video.mp4')

                with patch('downloader.yt_dlp.YoutubeDL', FakeYDL):
                    downloader = Downloader(auto_update=False)
                    request = DownloadRequest(url='https://example.com/video', output_path=directory)
                    if outcome == 'success':
                        result = downloader.download(request, is_cancelled=lambda: cancelled[0])
                        self.assertEqual(Path(result).name, "video (2).mp4")
                        self.assertEqual(Path(result).read_bytes(), b"complete")
                        self.assertEqual(existing.read_bytes(), b"existing")
                    else:
                        error = DownloadError if outcome == 'failure' else DownloadCancelled
                        with self.assertRaises(error):
                            downloader.download(request, is_cancelled=lambda: cancelled[0])
                        self.assertEqual(existing.read_bytes(), b'existing')
                self.assertTrue(work_dirs)
                self.assertTrue(all(not folder.exists() for folder in work_dirs))
                self.assertEqual((other / 'other.part').read_bytes(), b'other')
                self.assertEqual(set(root.iterdir()), {existing, other, root / "video (2).mp4"} if outcome == "success" else {existing, other})


if __name__ == '__main__':
    unittest.main()
