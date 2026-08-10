"""YouTubeダウンローダーアプリケーションのエントリーポイント。

このモジュールは以下の機能を提供します：
- グローバル例外ハンドラ（クラッシュログ）
- Frozen環境（.app）用のQt/Python設定
- 起動時の依存ツール診断
"""

from __future__ import annotations

import os
import sys
import traceback
import logging
from pathlib import Path


def _setup_frozen_environment() -> None:
    """PyInstallerでビルドされたアプリ用の環境設定を行う。"""
    if not getattr(sys, 'frozen', False):
        return
    
    # アプリケーションのベースパスを取得
    if hasattr(sys, '_MEIPASS'):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(sys.executable).parent
    
    # Qt プラグインパスの設定
    # PySide6のプラグインが見つからない場合のフォールバック
    qt_plugin_path = base_path / "PySide6" / "plugins"
    if qt_plugin_path.exists():
        os.environ["QT_PLUGIN_PATH"] = str(qt_plugin_path)
    
    # ライブラリパスの設定（dylib検索用）
    lib_path = base_path / "lib"
    if lib_path.exists():
        current_dyld = os.environ.get("DYLD_LIBRARY_PATH", "")
        os.environ["DYLD_LIBRARY_PATH"] = f"{lib_path}:{current_dyld}"
    
    # PATH環境変数の補完（ffmpeg, node用）
    paths_to_add = [
        "/opt/homebrew/bin",  # Apple Silicon Mac
        "/usr/local/bin",     # Intel Mac / Homebrew legacy
        "/usr/bin",
        "/bin"
    ]
    current_path = os.environ.get("PATH", "")
    new_paths = [p for p in paths_to_add if p not in current_path]
    if new_paths:
        os.environ["PATH"] = os.pathsep.join(new_paths + [current_path])


def _setup_exception_handler(logger: logging.Logger) -> None:
    """グローバル例外ハンドラを設定する。"""
    
    def handle_exception(exc_type, exc_value, exc_traceback):
        """未処理例外をログに記録し、可能ならダイアログを表示する。"""
        # KeyboardInterruptは通常通り処理
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        # 例外をログに記録
        logger.critical(
            "未処理の例外が発生しました",
            exc_info=(exc_type, exc_value, exc_traceback)
        )
        
        # クラッシュレポートをファイルに保存
        crash_log_path = Path.home() / "Library" / "Logs" / "YoutubeDownloader" / "crash.log"
        crash_log_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(crash_log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"Crash at: {__import__('datetime').datetime.now().isoformat()}\n")
                f.write(f"{'='*60}\n")
                traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
        except Exception:
            pass  # ログ書き込み失敗は無視
        
        # GUIが利用可能ならダイアログを表示
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app:
                error_msg = f"{exc_type.__name__}: {exc_value}"
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Critical)
                msg_box.setWindowTitle("アプリケーションエラー")
                msg_box.setText("予期しないエラーが発生しました。")
                msg_box.setInformativeText(error_msg)
                msg_box.setDetailedText(
                    "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
                )
                msg_box.exec()
        except Exception:
            pass  # GUI表示失敗は無視
    
    sys.excepthook = handle_exception


def _run_startup_diagnostics(logger: logging.Logger) -> None:
    """起動時に依存ツールの存在を確認する。"""
    import shutil
    
    tools = {
        "ffmpeg": "動画/音声の変換に必要",
        "node": "高画質ダウンロードに推奨（オプション）"
    }
    
    for tool, description in tools.items():
        path = shutil.which(tool)
        if path:
            logger.info(f"依存ツール検出: {tool} -> {path}")
        else:
            logger.warning(f"依存ツール未検出: {tool} ({description})")


def main() -> None:
    """アプリケーションを初期化してGUIループを開始する。"""
    # 1. Frozen環境の設定（インポート前に実行）
    _setup_frozen_environment()
    
    # 2. ロギング設定
    from utils.logging_config import configure_logging
    logger = configure_logging()
    logger.info("YouTube Downloader starting...")
    logger.info(f"Python: {sys.version}")
    logger.info(f"Frozen: {getattr(sys, 'frozen', False)}")
    
    # 3. 例外ハンドラ設定
    _setup_exception_handler(logger)
    
    # 4. 起動診断
    _run_startup_diagnostics(logger)
    
    # 5. GUIの起動
    try:
        from qt_app import run as run_gui
        logger.info("Starting GUI...")
        run_gui()
    except Exception as e:
        logger.critical(f"GUI起動に失敗しました: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
