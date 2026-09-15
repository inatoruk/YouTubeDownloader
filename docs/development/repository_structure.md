# 現在のリポジトリ構造

コードのパッケージ集約は実施せず、既存のimportと起動入口を維持しています。

```text
YoutubeDownloader/
├── main.py                     起動・診断・例外処理
├── qt_app.py                   画面全体と操作の接続
├── queue_manager.py            状態・並列実行・ワーカー
├── downloader.py               yt-dlpの呼び出し
├── theme.py                    見た目・状態アイコン
├── widgets/                    URL・形式・キュー・進捗パネル
├── utils/logging_config.py     ログ設定（名前空間パッケージ）
├── scripts/                    更新・検証・構造図の生成
├── docs/
│   ├── user/                   現行の操作方法
│   ├── development/            構成・動作・検証・ビルド
│   └── archive/                過去の要件・検討履歴
├── README.md                   最初に読む案内
├── requirements.txt            実行依存
├── requirements-dev.txt        ビルド依存
├── YoutubeDownloader.spec      ビルド定義
├── folder-map.html             ローカル構造図（Git対象外）
├── folder-map-organized.html   整理後の構造図（Git対象外）
├── 整理計画.md                 方針と実施記録への案内
├── .venv/                     開発環境（保持）
├── build/                     中間生成物・検証記録
├── dist/                      検証済み出力・旧版の退避
└── 削除候補_2026-09-09/        ユーザーによる手動削除待ち
```

旧ビルドは保持し、旧ルート版.appはdist/backups/pre-organization-root/に保管しています。利用先は/Applications/YoutubeDownloader.appです。生成物の内容はビルドや手動削除によって変化します。

## 依存関係

main → qt_app → queue_manager → downloader → yt-dlp が主経路です。qt_appはdownloader・theme・widgetsも直接利用します。themeはqueue_manager.ItemStatusを参照します。widgetsはtheme、キューパネルは状態モデル、URLパネルのチャンネル取得はdownloaderを参照します。mainはutils.logging_configを利用します。

widgetsの6ファイルは `__init__.py`、url_panel.py、format_panel.py、queue_panel.py、progress_panel.py、smooth_progress.pyです。Pythonソース本体はルート5＋widgets 6＋utils 1の12ファイルです（補助スクリプトを除く）。

specはmain.pyからimportを解析してPythonコードを収集します。Pythonソースをdatasとして二重同梱しません。utils/__init__.pyは追加していません。

[ビルド・更新](build_and_update.md) / [検証項目](testing.md)
