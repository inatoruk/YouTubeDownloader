"""ロギング設定ユーティリティ。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path.home() / "Library" / "Logs" / "YoutubeDownloader"
LOG_FILE = LOG_DIR / "app.log"
_MAX_BYTES = 1_048_576  # 1MB
_BACKUP_COUNT = 5
_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """ファイル出力付きロギングを構成し、アプリケーションロガーを返す。"""
    global _CONFIGURED

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not _CONFIGURED:
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        if not any(type(handler) is logging.StreamHandler for handler in root_logger.handlers):
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setFormatter(formatter)
            root_logger.addHandler(stream_handler)

        logging.captureWarnings(True)
        _CONFIGURED = True

    return logging.getLogger("youtube_downloader")
