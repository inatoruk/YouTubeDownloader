> 過去の要件・検討履歴です。現行の操作方法は [ユーザーマニュアル](../user/USER_MANUAL.md) を参照してください。

# YouTube Downloader for macOS

## 概要
- YouTubeのURLを入力して動画または音声をダウンロードするmacOS向けアプリケーション。
- GUIはTkinter製で、解像度選択・MP4/MP3切り替え・保存先指定・進捗表示に対応。
- yt-dlpを利用し、起動時に自動アップデートを試行します。

## 前提条件
- macOS Ventura以降（Apple Silicon / Intel いずれも可）。
- Python 3.12系（Homebrew推奨）。未導入の場合は以下でインストール：
  ```bash
  brew install python@3.12
  ```
- FFmpeg（音声抽出に必要）。未導入なら：
  ```bash
  brew install ffmpeg
  ```

## セットアップ
1. リポジトリ直下で仮想環境を作成し、有効化します。
   ```bash
   cd /Users/jun/Desktop/YoutubeDownloader
   /opt/homebrew/bin/python3.12 -m venv .venv
   source .venv/bin/activate
   ```
2. 依存パッケージをインストールします。
   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

## 利用方法
- ターミナル操作を省略したい場合は `StartYoutubeDownloader.command` をダブルクリックしてください。初回は仮想環境の作成と依存インストールを自動で実行し、そのままGUIが起動します。
- 手動で起動する場合：
  ```bash
  source .venv/bin/activate
  python main.py
  ```
- フォームへYouTube URLを入力し、フォーマット（動画/音声）、解像度、保存先を設定して「ダウンロード」をクリックします。
- 進捗バーやステータスメッセージで状況を確認できます。完了時は保存パス付きのダイアログを表示します。
- ログファイルは `~/Library/Logs/YoutubeDownloader/app.log` に出力されます。

## トラブルシューティング
- `externally-managed-environment` と表示されたら仮想環境が有効になっていません。`source .venv/bin/activate` を実行してから再度スタートしてください。
- GUIが起動せず `Abort trap: 6` と出る場合、システム付属の旧Pythonが使われています。Homebrew版Pythonで仮想環境を作り直すか、`StartYoutubeDownloader.command` のメッセージに従って対応してください。
- `StartYoutubeDownloader.command` で「Homebrew版Pythonが見つかりません」と表示された場合は `brew install python@3.12` を実行した後、もう一度ダブルクリックしてください。

## テスト
- `docs/testing.md` に手動テスト項目と将来的な自動テスト方針をまとめています。
- 代表的な手動テスト：
  - URL未入力時のバリデーション。
  - 保存先変更とフォーマット/解像度切替の確認。
  - 正常系ダウンロードで進捗・完了ダイアログを確認。
  - エラー発生時（ネットワーク切断・保存先権限なし）の挙動確認。
