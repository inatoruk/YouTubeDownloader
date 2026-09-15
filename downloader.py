"""yt-dlpを利用したダウンロード処理。"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Callable, Optional, Sequence

import yt_dlp

ProgressCallback = Callable[[dict], None]

# yt-dlp がこの日数より古い場合、YouTube の仕様変更に追随できず
# ダウンロードが 403 等で失敗する可能性が高いとみなす。
STALE_AFTER_DAYS = 45


def yt_dlp_version() -> str:
    """実際にロードされている yt-dlp のバージョン文字列を返す。"""
    return getattr(yt_dlp.version, "__version__", "unknown")


def yt_dlp_age_days() -> Optional[int]:
    """yt-dlp のリリース日からの経過日数を返す。

    yt-dlp のバージョンは "2026.08.19" のような日付形式なので、
    そこから古さを判定できる。解釈できない場合は None。
    """
    match = re.match(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})", yt_dlp_version())
    if not match:
        return None
    try:
        released = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return (date.today() - released).days


def is_yt_dlp_stale() -> bool:
    """yt-dlp が古く、ダウンロード失敗の原因になりうるかを判定する。"""
    age = yt_dlp_age_days()
    return age is not None and age > STALE_AFTER_DAYS


# リトライしても結果が変わらない（恒久的な）失敗のパターン。
# これらに一致した場合は即座に諦め、無駄な再試行で時間を浪費しない。
_PERMANENT_ERROR_PATTERNS = (
    "403",
    "forbidden",
    "video unavailable",
    "private video",
    "members-only",
    "members only",
    "removed by the uploader",
    "account associated with this video has been terminated",
    "sign in to confirm your age",
    "is not available in your country",
    "this live event will begin",
    # ブラウザからcookieを読み取れない（未インストール・プロファイル不在など）
    "cookies database",
)


def is_permanent_error(message: str) -> bool:
    """再試行しても回復しないエラーかどうかを判定する。"""
    low = message.lower()
    return any(pattern in low for pattern in _PERMANENT_ERROR_PATTERNS)


# YouTube のボット検出（「Sign in to confirm you’re not a bot」）を受けたときに
# cookie を読み取るブラウザ。ログイン済みの YouTube セッションで検出を回避する。
COOKIE_BROWSER = "chrome"


def is_bot_check_error(message: str) -> bool:
    """YouTube のボット検出（ログイン要求）によるエラーかどうかを判定する。

    短時間に大量のダウンロードを行うと、回線(IP)単位で全動画が弾かれるようになる。
    メッセージ中のアポストロフィは ’ (U+2019) になるため、その後ろの語句で判定する。
    """
    return "not a bot" in message.lower()


def describe_error(message: str, cookies_used: bool = False) -> str:
    """yt-dlp の生エラーを、次に何をすべきか分かる日本語に変換する。

    Args:
        cookies_used: 失敗した試行でブラウザの cookie を使っていたか。
            ボット検出時の案内内容を切り替えるために使う。
    """
    low = message.lower()
    if is_bot_check_error(message):
        if cookies_used:
            return (
                "YouTubeにボットと判定されました。Chromeのcookieを使っても解除されませんでした。"
                " ChromeでYouTubeにログインしているか、キーチェーンの確認で「常に許可」を"
                "選んだかを確認してください。短時間に大量にダウンロードすると発生するため、"
                "時間をおいて再試行してください。"
            )
        return (
            "YouTubeにボットと判定されました。短時間に大量にダウンロードすると発生します。"
            " 時間をおいて再試行してください。"
        )
    if "cookies database" in low:
        return (
            f"ブラウザ({COOKIE_BROWSER})のcookieを読み取れませんでした。"
            " ブラウザがインストールされ、YouTubeにログインしているか確認してください。"
        )
    if "403" in message or "forbidden" in low:
        hint = "YouTubeにアクセスを拒否されました (403)。"
        if is_yt_dlp_stale():
            age = yt_dlp_age_days()
            hint += (
                f" ダウンロードエンジン(yt-dlp {yt_dlp_version()})が"
                f"{age}日前のもので古いことが原因の可能性が高いです。更新してください。"
            )
        else:
            hint += " 時間をおいて再試行してください。"
        return hint
    if "video unavailable" in low or "removed by the uploader" in low:
        return "この動画は削除されたか非公開です。"
    if "private video" in low:
        return "非公開動画のためダウンロードできません。"
    if "members-only" in low or "members only" in low:
        return "メンバー限定動画のためダウンロードできません。"
    if "sign in to confirm your age" in low:
        return "年齢確認が必要な動画のためダウンロードできません。"
    if "is not available in your country" in low:
        return "お住まいの地域では視聴できない動画です。"
    if "ffmpeg" in low:
        return "ffmpegの処理に失敗しました。`brew install ffmpeg` で導入・更新してください。"
    if "timed out" in low or "timeout" in low or "connection" in low:
        return "ネットワークエラーが発生しました。接続を確認してください。"
    return message


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


class DownloadCancelled(Exception):
    """ユーザー操作によるキャンセル。

    通常の失敗と違いリトライしてはならない。以前はキャンセルが
    汎用の Exception として送出され、リトライループに飲み込まれた結果、
    停止ボタンを押しても再ダウンロードが2回走っていた。
    """


class Downloader:
    """yt-dlpを用いたダウンロード処理ラッパー。"""

    _global_update_checked = False

    # ボット検出を一度受けたら、以後このプロセスでは cookie 経路を使う。
    # 検出された回線で cookie なしのリクエストを重ねても失敗が増えるだけのため。
    # 全ワーカーで共有するのでクラス属性にしている。
    _cookies_enabled = False

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

    def _base_options(self) -> dict:
        """全ての yt-dlp 呼び出しに共通するオプション。"""
        options: dict = {"quiet": True, "no_warnings": True, "no_color": True, "socket_timeout": 15}
        if Downloader._cookies_enabled:
            options.update(self._cookie_options())
        return options

    @staticmethod
    def _cookie_options() -> dict:
        """ボット検出を回避するためのオプション（ブラウザの cookie ＋ JS チャレンジ解読）。

        cookie を渡すと yt-dlp は cookie 非対応の android 系クライアントを使えなくなり、
        JS チャレンジの解読が必要な web クライアントに切り替わる。yt-dlp の既定の
        JS ランタイムは deno のみなので、導入済みの node を明示し、解読スクリプト(ejs)の
        取得を許可する。cookie だけでは「No video formats found」になることを確認済み。
        いずれも Python API のパラメータとして有効（yt_dlp/YoutubeDL.py 参照）。
        """
        return {
            "cookiesfrombrowser": (COOKIE_BROWSER, None, None, None),
            "js_runtimes": {"node": {}},
            "remote_components": ["ejs:github"],
        }

    def _enable_cookies(self) -> None:
        """以後の yt-dlp 呼び出しを cookie 経路に切り替える。"""
        if not Downloader._cookies_enabled:
            Downloader._cookies_enabled = True
            self._logger.warning(
                "YouTubeのボット検出を受けたため、以後は %s のcookieを使用します",
                COOKIE_BROWSER,
            )

    def _extract(self, url: str, extra: dict, handle: Callable[[Optional[dict]], object], is_cancelled=None):
        """ダウンロードせずに情報を取得し、handle(info) の結果を返す。

        ボット検出を受けたら cookie 経路で1度だけやり直す。handle は yt-dlp の
        セッションが開いている間に呼ぶ（従来どおり with ブロック内で処理する）。
        """
        for _ in range(2):
            self._check_cancelled(is_cancelled)
            used_cookies = Downloader._cookies_enabled
            options = {**self._base_options(), **extra}
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=False)
                    self._check_cancelled(is_cancelled)
                    return handle(info)
            except Exception as exc:
                if is_bot_check_error(str(exc)) and not used_cookies:
                    self._enable_cookies()
                    continue
                raise
        return None

    def download(
        self,
        request: DownloadRequest,
        progress_hooks: Optional[Sequence[ProgressCallback]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> str:
        """専用の作業フォルダで取得し、完成したファイルだけ保存先へ移す。

        中断・失敗時は、このダウンロードの途中ファイルだけを削除する。
        既存ファイルや並列ダウンロードの作業ファイルには触れない。
        """
        if is_cancelled and is_cancelled():
            raise DownloadCancelled("キャンセルされました")
        output_dir = Path(request.output_path).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".youtube-download-", dir=output_dir) as work_dir:
            completed = Path(self._download_to_directory(
                replace(request, output_path=work_dir), progress_hooks, is_cancelled,
            ))
            # 変換・結合中の停止要求も、完成ファイルを保存する前に反映する。
            if is_cancelled and is_cancelled():
                raise DownloadCancelled("キャンセルされました")
            number = 1
            while True:
                name = completed.name if number == 1 else f"{completed.stem} ({number}){completed.suffix}"
                destination = output_dir / name
                try:
                    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
                    break
                except FileExistsError:
                    number += 1
            os.close(fd)
            try:
                self._check_cancelled(is_cancelled)
                os.replace(completed, destination)
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
        self._logger.info("Download saved: %s", destination)
        return str(destination)

    def _download_to_directory(
        self,
        request: DownloadRequest,
        progress_hooks: Optional[Sequence[ProgressCallback]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> str:
        """ダウンロード処理を実行する。

        Args:
            is_cancelled: キャンセル要求の有無を返す関数。yt-dlp が内部で
                例外を包み替えても確実にキャンセルを検出できるよう、
                例外型だけに頼らずこの関数でも判定する。

        Returns:
            ダウンロードしたファイルのパス

        Raises:
            DownloadCancelled: ユーザーがキャンセルした場合（リトライしない）
            DownloadError: ダウンロードに失敗した場合
        """
        output_dir = Path(request.output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        def cancelled() -> bool:
            return is_cancelled is not None and is_cancelled()

        last_error: Optional[Exception] = None
        last_used_cookies = False
        attempt = 0
        while attempt < self._max_retries:
            attempt += 1
            # リトライ前に毎回チェックし、キャンセル後の再ダウンロードを防ぐ
            if cancelled():
                raise DownloadCancelled("キャンセルされました")
            # cookie 経路への切り替えを反映するため、オプションは試行ごとに組み立てる
            used_cookies = Downloader._cookies_enabled
            ydl_opts = self._build_options(request, progress_hooks)
            try:
                self._logger.info(
                    "Start download (attempt %s/%s, cookies=%s): url=%s",
                    attempt, self._max_retries, used_cookies, request.url,
                )
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(request.url, download=True)
                    if info:
                        downloads = info.get("requested_downloads") or [info]
                        if len(downloads) != 1:
                            raise DownloadError("単一動画の完成ファイルを確認できませんでした")
                        final_path = Path(downloads[0].get("filepath") or "")
                        expected_ext = request.audio_format.lower() if request.format_type == "audio" else "mp4"
                        if (not final_path.is_file() or final_path.suffix.lower() != f".{expected_ext}"
                                or not final_path.resolve().is_relative_to(output_dir.resolve())):
                            raise DownloadError("変換後の完成ファイルを確認できませんでした")
                        return str(final_path)
                raise DownloadError(f"ダウンロード情報の取得に失敗しました: {request.url}")
            except DownloadCancelled:
                raise
            except Exception as exc:
                # キャンセル由来の失敗はリトライせず即座に抜ける。
                # yt-dlp が例外を包み替えても検出できるようフラグでも確認する。
                if cancelled():
                    self._logger.info("Download cancelled: %s", request.url)
                    raise DownloadCancelled("キャンセルされました") from exc
                last_error = exc
                last_used_cookies = used_cookies
                self._logger.warning("Download failed (attempt %s): %s", attempt, exc)
                if is_bot_check_error(str(exc)):
                    if not used_cookies:
                        # cookie 経路に切り替えて即座にやり直す。切り替えは試行回数に
                        # 数えない（次の試行は必ず cookie を使うため無限ループしない）。
                        self._enable_cookies()
                        attempt -= 1
                        continue
                    # cookie を使っても検出される場合、すぐ再試行しても結果は変わらない
                    self._logger.info("Bot check persists even with cookies, giving up")
                    break
                # 403やdeleted等、再試行しても結果が変わらない失敗は即座に諦める。
                # （以前はここで無駄に3回リトライしていた）
                if is_permanent_error(str(exc)):
                    self._logger.info(
                        "Permanent error detected, skipping retries: %s", exc
                    )
                    break
                if attempt < self._max_retries:
                    sleep_seconds = min(5, attempt)
                    self._logger.info("Retrying in %s seconds", sleep_seconds)
                    deadline = time.monotonic() + sleep_seconds
                    while time.monotonic() < deadline:
                        self._check_cancelled(is_cancelled)
                        time.sleep(min(0.1, max(0, deadline - time.monotonic())))

        raise DownloadError(
            describe_error(str(last_error), cookies_used=last_used_cookies)
        ) from last_error

    @staticmethod
    def _check_cancelled(is_cancelled):
        if is_cancelled and is_cancelled():
            raise DownloadCancelled("キャンセルされました")

    def fetch_info(self, url: str, is_cancelled=None) -> Optional[dict]:
        """動画の情報をダウンロードせずに取得する。

        Returns:
            動画情報の辞書（title, duration, thumbnail等）。
            取得に失敗した場合は None。
        """
        def summarize(info: Optional[dict]) -> Optional[dict]:
            if not info:
                return None
            return {
                "title": info.get("title", ""),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail", ""),
                "uploader": info.get("uploader", ""),
                "view_count": info.get("view_count"),
                "filesize": self._format_filesize(info.get("filesize") or info.get("filesize_approx")),
                "filesize_bytes": info.get("filesize") or info.get("filesize_approx"),
            }

        try:
            return self._extract(url, {"noplaylist": True, "skip_download": True}, summarize, is_cancelled)
        except DownloadCancelled:
            raise
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

    def extract_channel_urls(self, channel_url: str, is_cancelled=None) -> list[str]:
        """チャンネルURLから全動画URLのリストを抽出する。

        yt-dlpの extract_flat を使い、チャンネル内の全エントリを取得する。

        Returns:
            動画URLのリスト。
        """
        urls: list[str] = []

        def collect(info: Optional[dict]) -> None:
            if info and "entries" in info:
                for entry in info["entries"]:
                    self._check_cancelled(is_cancelled)
                    if entry is None:
                        continue
                    # ネストされたプレイリスト（チャンネルの「動画」タブなど）を再帰的に展開
                    if "entries" in entry:
                        for sub_entry in entry["entries"]:
                            self._check_cancelled(is_cancelled)
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

        try:
            self._extract(channel_url, {"extract_flat": "in_playlist", "noplaylist": False, "lazy_playlist": True}, collect, is_cancelled)
        except DownloadCancelled:
            raise
        except Exception as exc:
            self._logger.error("Channel extraction failed: %s", exc)
            raise DownloadError(f"チャンネルの展開に失敗しました: {channel_url}") from exc
        return urls

    def extract_playlist_urls(self, playlist_url: str, is_cancelled=None) -> list[str]:
        """プレイリストURLから個別の動画URLリストを抽出する。

        Returns:
            動画URLのリスト。
        """
        urls: list[str] = []

        def collect(info: Optional[dict]) -> None:
            if info and "entries" in info:
                for entry in info["entries"]:
                    self._check_cancelled(is_cancelled)
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

        try:
            self._extract(playlist_url, {"extract_flat": "in_playlist", "noplaylist": False, "lazy_playlist": True}, collect, is_cancelled)
        except DownloadCancelled:
            raise
        except Exception as exc:
            self._logger.error("Playlist extraction failed: %s", exc)
            raise DownloadError(f"プレイリストの展開に失敗しました: {playlist_url}") from exc
        return urls

    def _ensure_updated(self) -> None:
        """yt-dlp を最新化する（プロセスにつき1回だけ実行）。

        yt-dlp は YouTube の仕様変更に追随するため頻繁に更新される。
        古いままだとダウンロードが 403 等で失敗するため、ここで更新を試みる。
        """
        if not self._auto_update or Downloader._global_update_checked:
            return
        Downloader._global_update_checked = True

        age = yt_dlp_age_days()
        self._logger.info(
            "yt-dlp version: %s (%s日前)", yt_dlp_version(),
            age if age is not None else "不明",
        )

        # Frozen (.app) では yt-dlp が PYZ アーカイブに固められているため
        # 自己更新できない。古い場合は警告を残し、UI側で再ビルドを促す。
        if getattr(sys, "frozen", False):
            if is_yt_dlp_stale():
                self._logger.warning(
                    "同梱の yt-dlp (%s) が %s日前のものです。"
                    "YouTubeの仕様変更でダウンロードが失敗する可能性があります。"
                    "アプリの再ビルドが必要です。",
                    yt_dlp_version(), age,
                )
            else:
                self._logger.info("Frozen環境のため自己更新はスキップします")
            return

        # `yt_dlp -U` は単体バイナリ版専用で、pip導入版では動作しない。
        # そのため pip 経由で更新する。
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"]
        try:
            self._logger.info("Checking yt-dlp updates via pip")
            result = subprocess.run(
                cmd, check=True, capture_output=True, text=True, timeout=180
            )
        except subprocess.CalledProcessError as exc:
            self._logger.warning("yt-dlp update failed: %s", exc.stderr or exc)
        except subprocess.TimeoutExpired:
            self._logger.warning("yt-dlp update timed out")
        else:
            if "Successfully installed" in (result.stdout or ""):
                self._logger.info(
                    "yt-dlp を更新しました。次回起動時から反映されます。"
                )
            else:
                self._logger.info("yt-dlp は最新です (%s)", yt_dlp_version())

    def _build_options(
        self,
        request: DownloadRequest,
        progress_hooks: Optional[Sequence[ProgressCallback]],
    ) -> dict:
        output_dir = Path(request.output_path)
        
        options: dict = {
            **self._base_options(),
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "noplaylist": True,
            "ignoreerrors": False,
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
            options["postprocessors"] = [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}]

        # js_runtimes / remote_components は Python API でも有効なパラメータ。
        # 通常は cookie なしの既定クライアントで十分なため指定せず、
        # ボット検出時のみ _cookie_options() で有効にする。

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
