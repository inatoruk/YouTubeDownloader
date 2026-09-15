"""Real yt-dlp/FFmpeg conversion using a tiny local fixture; no network."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import yt_dlp
from yt_dlp.extractor.common import InfoExtractor
from downloader import Downloader, DownloadRequest


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe not installed')
class MediaConversionTests(unittest.TestCase):
    def test_local_webm_to_mp4_mp3_and_wav(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'fixture.webm'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=32x32:r=5',
                            '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '0.4',
                            '-c:v', 'libvpx-vp9', '-c:a', 'libopus', str(source)], check=True)
            class LocalIE(InfoExtractor):
                _VALID_URL = r'fixture:(?P<id>\w+)'
                def _real_extract(self, url):
                    return {'id': 'local', 'title': 'local', 'formats': [{
                        'format_id': 'local', 'url': source.as_uri(), 'ext': 'webm',
                        'vcodec': 'vp9', 'acodec': 'opus', 'height': 32,
                    }]}
            real_ydl = yt_dlp.YoutubeDL
            def local_ydl(options):
                options = {**options, 'enable_file_urls': True, 'noprogress': True}
                ydl = real_ydl(options, auto_init=False)
                ydl.add_info_extractor(LocalIE())
                return ydl
            for format_type, codec, extension in [('video', 'MP3', 'mp4'), ('audio', 'MP3', 'mp3'), ('audio', 'WAV', 'wav')]:
                with self.subTest(extension=extension), patch('downloader.yt_dlp.YoutubeDL', local_ydl):
                    output = Downloader(max_retries=1, auto_update=False).download(
                        DownloadRequest('fixture:local', str(root / 'output'), format_type=format_type, audio_format=codec))
                    self.assertEqual(Path(output).suffix, '.' + extension)
                    self.assertGreater(Path(output).stat().st_size, 0)
                    subprocess.run(['ffprobe', '-v', 'error', output], check=True)
            self.assertEqual(len(list((root / 'output').iterdir())), 3)
            self.assertTrue(source.exists())


if __name__ == '__main__': unittest.main()
