"""yt-dlpを利用したダウンロード処理。"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

import yt_dlp

ProgressCallback = Callable[[dict], None]


@dataclass
class DownloadRequest:
    """ダウンロード要求のパラメータ。"""

    url: str
    output_path: str
    format_type: str = "video"  # "video" or "audio"
    resolution: str = "best"  # "best", "720p", "1080p", "1440p", "2160p"
    audio_format: str = "MP3"  # "MP3" or "WAV"
    bitrate: str = "320kbps"  # "320kbps", "256kbps", "192kbps", "128kbps"


class DownloadError(Exception):
    """ダウンロード処理中の例外。"""


class Downloader:
    """yt-dlpを用いたダウンロード処理ラッパー。"""

    _global_update_checked = False

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        max_retries: int = 3,
        auto_update: bool = True,
    ) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._max_retries = max(1, max_retries)
        self._auto_update = auto_update
        
        # macOSのGUIから実行された場合など、PATH環境変数が不足していることがあるため補完する
        self._update_environment_path()

    def _update_environment_path(self) -> None:
        """PyInstallerなどで凍結された環境用にPATHを追加する"""
        current_path = os.environ.get("PATH", "")
        paths_to_add = [
            "/opt/homebrew/bin",  # Apple Silicon Mac standard
            "/usr/local/bin",     # Intel Mac standard
            "/usr/bin",
            "/bin"
        ]
        
        new_paths = []
        for p in paths_to_add:
            if p not in current_path:
                new_paths.append(p)
        
        if new_paths:
            # 既存のPATHの先頭に追加して優先させる
            os.environ["PATH"] = os.pathsep.join(new_paths + [current_path])
            self._logger.info("Updated PATH for frozen environment: %s", os.environ["PATH"])

    def download(
        self,
        request: DownloadRequest,
        progress_hooks: Optional[Sequence[ProgressCallback]] = None,
    ) -> str:
        """ダウンロード処理を実行する。
        
        Returns:
            ダウンロードしたファイルのパス
        """
        output_dir = Path(request.output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        ydl_opts = self._build_options(request, progress_hooks)

        last_error: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                self._logger.info(
                    "Start download (attempt %s/%s): url=%s", attempt, self._max_retries, request.url
                )
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(request.url, download=True)
                    if info:
                        # ダウンロードしたファイルのパスを取得
                        if request.format_type == "audio":
                            ext = request.audio_format.lower()
                        else:
                            ext = "mp4"
                        filename = ydl.prepare_filename(info)
                        # 拡張子を正しいものに置換
                        final_path = Path(filename).with_suffix(f".{ext}")
                        self._logger.info("Download completed: %s", final_path)
                        return str(final_path)
                raise DownloadError(f"ダウンロード情報の取得に失敗しました: {request.url}")
            except Exception as exc:
                last_error = exc
                self._logger.warning("Download failed (attempt %s): %s", attempt, exc)
                if attempt < self._max_retries:
                    sleep_seconds = min(5, attempt)
                    self._logger.info("Retrying in %s seconds", sleep_seconds)
                    time.sleep(sleep_seconds)

        raise DownloadError(f"ダウンロードに失敗しました: {request.url}") from last_error

    def fetch_info(self, url: str) -> Optional[dict]:
        """動画の情報をダウンロードせずに取得する。

        Returns:
            動画情報の辞書（title, duration, thumbnail等）。
            取得に失敗した場合は None。
        """
        opts = {
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "noplaylist": True,
            "skip_download": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    return {
                        "title": info.get("title", ""),
                        "duration": info.get("duration"),
                        "thumbnail": info.get("thumbnail", ""),
                        "uploader": info.get("uploader", ""),
                        "view_count": info.get("view_count"),
                        "filesize": self._format_filesize(info.get("filesize") or info.get("filesize_approx")),
                    }
        except Exception as exc:
            self._logger.warning("Info fetch failed for %s: %s", url, exc)
        return None

    def _format_filesize(self, size: Optional[int]) -> Optional[str]:
        """バイト数を人間が読みやすい形式に変換する。"""
        if size is None:
            return None
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"

    def extract_channel_urls(self, channel_url: str) -> list[str]:
        """チャンネルURLから全動画URLのリストを抽出する。

        yt-dlpの extract_flat を使い、チャンネル内の全エントリを取得する。

        Returns:
            動画URLのリスト。
        """
        opts = {
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "extract_flat": "in_playlist",
            "noplaylist": False,
        }
        urls: list[str] = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                if info and "entries" in info:
                    for entry in info["entries"]:
                        if entry is None:
                            continue
                        # ネストされたプレイリスト（チャンネルの「動画」タブなど）を再帰的に展開
                        if "entries" in entry:
                            for sub_entry in entry["entries"]:
                                if sub_entry and sub_entry.get("url"):
                                    video_url = sub_entry["url"]
                                    if not video_url.startswith("http"):
                                        video_url = f"https://www.youtube.com/watch?v={video_url}"
                                    urls.append(video_url)
                        elif entry.get("url"):
                            video_url = entry["url"]
                            if not video_url.startswith("http"):
                                video_url = f"https://www.youtube.com/watch?v={video_url}"
                            urls.append(video_url)
                    self._logger.info(
                        "Extracted %d URLs from channel: %s", len(urls), channel_url
                    )
                elif info and info.get("webpage_url"):
                    urls.append(info["webpage_url"])
        except Exception as exc:
            self._logger.error("Channel extraction failed: %s", exc)
            raise DownloadError(f"チャンネルの展開に失敗しました: {channel_url}") from exc
        return urls

    def extract_playlist_urls(self, playlist_url: str) -> list[str]:
        """プレイリストURLから個別の動画URLリストを抽出する。

        Returns:
            動画URLのリスト。
        """
        opts = {
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "extract_flat": "in_playlist",
            "noplaylist": False,
        }
        urls: list[str] = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
                if info and "entries" in info:
                    for entry in info["entries"]:
                        if entry and entry.get("url"):
                            video_url = entry["url"]
                            # フルURLに変換
                            if not video_url.startswith("http"):
                                video_url = f"https://www.youtube.com/watch?v={video_url}"
                            urls.append(video_url)
                    self._logger.info(
                        "Extracted %d URLs from playlist: %s", len(urls), playlist_url
                    )
                elif info and info.get("webpage_url"):
                    # プレイリストではなく単一動画だった場合
                    urls.append(info["webpage_url"])
        except Exception as exc:
            self._logger.error("Playlist extraction failed: %s", exc)
            raise DownloadError(f"プレイリストの展開に失敗しました: {playlist_url}") from exc
        return urls

    def _ensure_updated(self) -> None:
        # Frozenアプリの場合は自分自身を更新できないためスキップ
        # sys.executableがpythonインタープリタではなくアプリ実行ファイルになるため
        if getattr(sys, 'frozen', False):
            self._logger.info("Skipping yt-dlp update in frozen environment")
            return

        if not self._auto_update or Downloader._global_update_checked:
            return

        cmd = [sys.executable, "-m", "yt_dlp", "-U"]
        try:
            self._logger.info("Checking yt-dlp updates")
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        except subprocess.CalledProcessError as exc:
            self._logger.warning("yt-dlp update failed: %s", exc)
        except subprocess.TimeoutExpired:
            self._logger.warning("yt-dlp update timed out")
        else:
            self._logger.info("yt-dlp update complete")
        finally:
            Downloader._global_update_checked = True

    def _build_options(
        self,
        request: DownloadRequest,
        progress_hooks: Optional[Sequence[ProgressCallback]],
    ) -> dict:
        output_dir = Path(request.output_path)
        
        options: dict = {
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "noplaylist": True,
            "ignoreerrors": False,
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "progress_hooks": list(progress_hooks or []),
            "overwrites": True,
            "prefer_ffmpeg": True,
        }

        if request.format_type == "audio":
            # 音声ダウンロード
            codec = request.audio_format.lower()  # "mp3" or "wav"
            bitrate = request.bitrate.replace("kbps", "") if codec == "mp3" else None
            
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": bitrate,
            }]
        else:
            # 動画ダウンロード
            format_selector = self._build_format_selector(request.resolution)
            options["format"] = format_selector
            options["merge_output_format"] = "mp4"

        # 注意: js_runtimesやremote_componentsはCLI専用オプションであり、
        # Python APIでは互換性がないため使用しない。
        # 高解像度フォーマットの取得はyt-dlpのデフォルト動作に依存する。

        return options

    def _build_format_selector(self, resolution: str) -> str:
        if resolution == "best" or resolution is None:
            return "bestvideo+bestaudio/best"

        quality_map = {
            "720p": "720",
            "1080p": "1080",
            "1440p": "1440",
            "2160p": "2160",
        }
        height = quality_map.get(resolution, "1080")
        return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
