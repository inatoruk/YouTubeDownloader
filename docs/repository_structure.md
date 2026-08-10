# リポジトリ構造

このドキュメントでは、YouTube Downloader リポジトリのファイル構成と各ファイルの役割を説明します。

## ディレクトリツリー

```
YoutubeDownloader/
├── main.py                          # エントリーポイント
├── downloader.py                    # ダウンロード処理（yt-dlpラッパー）
├── gui/                             # GUIモジュール
│   ├── __init__.py                  # モジュール公開インターフェース
│   ├── main.py                      # Applicationクラス（メインウィンドウ）
│   ├── components.py                # UIコンポーネント群
│   ├── constants.py                 # 定数定義（設定値・オプション）
│   └── styles.py                    # テーマ・スタイル定義
├── gui_old.py                       # 旧GUIファイル（非推奨・残存）
├── utils/                           # ユーティリティモジュール
│   └── logging_config.py            # ログ設定
├── docs/                            # ドキュメント
│   ├── requirements.md              # 要件定義
│   ├── addrequirements.md           # 追加要件
│   ├── download_mechanism.md        # ダウンロード仕組み（概説）
│   ├── download_mechanism_precise.md # ダウンロード仕組み（詳細・事実ベース）
│   ├── testing.md                   # テスト項目
│   └── repository_structure.md      # 本ドキュメント
├── README.md                        # 利用ガイド
├── requirements.txt                 # Python依存パッケージ
├── Makefile                         # ビルド/実行コマンド
├── run.sh                           # 実行スクリプト（zsh）
└── StartYoutubeDownloader.command   # macOS用ダブルクリック起動
```

---

## 各ファイル・ディレクトリの詳細

### ルートディレクトリ

| ファイル | 役割 |
|---------|------|
| `main.py` | アプリケーションのエントリーポイント。ログ初期化後、GUIを起動する。 |
| `downloader.py` | yt-dlpを使用したダウンロード処理。`Downloader`クラス、`DownloadRequest`データクラス、`DownloadError`例外を提供。再試行ロジック（最大3回）、yt-dlp自動更新機能を含む。 |
| `gui_old.py` | 旧GUI実装（単一ファイル版）。現在は`gui/`パッケージに移行済み。互換性のため残存。 |
| `README.md` | 利用者向けガイド。前提条件、セットアップ手順、利用方法、トラブルシューティングを記載。 |
| `requirements.txt` | Python依存パッケージ（yt-dlp等）。`pip install -r requirements.txt`で導入。 |
| `Makefile` | `make install`（依存導入）、`make run`（起動）コマンドを提供。 |
| `run.sh` | zsh用起動スクリプト。仮想環境作成/有効化、依存インストール、アプリ起動を自動化。 |
| `StartYoutubeDownloader.command` | macOS用ダブルクリック起動ファイル。Finderからワンクリックで起動可能。 |

---

### gui/ ディレクトリ（GUIモジュール）

| ファイル | 役割 |
|---------|------|
| `__init__.py` | モジュール公開インターフェース。`run()`、`create_application()`を外部に公開。既存の`from gui import run`呼び出しとの互換性を保持。 |
| `main.py` | `Application`クラス（メインウィンドウ）。ダウンロード開始、進捗管理、イベントハンドリング、スレッド間通信（Queue）を担当。 |
| `components.py` | UIコンポーネント群。`HeaderSection`、`URLInputSection`、`FormatSection`、`OutputSection`、`ProgressSection`、`ControlSection`など、各セクションをクラス化。 |
| `constants.py` | 定数定義。アプリ名/バージョン、ウィンドウサイズ、解像度オプション（720p〜4320p）、音声フォーマット、ビットレート、レイアウト値、ステータスメッセージ等。 |
| `styles.py` | テーマ・スタイル定義（Obsidian Flowデザイン）。`ColorPalette`クラスでダークテーマのカラーパレット、`configure_style()`でttkスタイル設定を提供。 |

---

### utils/ ディレクトリ（ユーティリティ）

| ファイル | 役割 |
|---------|------|
| `logging_config.py` | ログ設定。`configure_logging()`関数でファイル出力（`~/Library/Logs/YoutubeDownloader/app.log`）とコンソール出力を構成。ローテーション（1MB、最大5世代）対応。 |

---

### docs/ ディレクトリ（ドキュメント）

| ファイル | 内容 |
|---------|------|
| `requirements.md` | 初期要件定義。機能要件、非機能要件、設計方針を記載。 |
| `addrequirements.md` | 追加要件。解像度追加、進捗表示改善、ショートカット、拡張子固定などの希望事項と回答。 |
| `download_mechanism.md` | ダウンロード仕組みの概説（初心者向け）。全体フロー、コンポーネント役割、例え話を含む。 |
| `download_mechanism_precise.md` | ダウンロード仕組みの詳細（事実ベース）。コード実装に基づく正確な技術仕様。 |
| `testing.md` | テスト項目。手動テスト項目、将来的な自動テスト方針。 |
| `repository_structure.md` | 本ドキュメント。リポジトリ構造の説明。 |

---

## モジュール依存関係

```
main.py
  ├── utils.logging_config  (ログ初期化)
  └── gui                   (GUI起動)
        ├── gui.main        (Applicationクラス)
        │     ├── downloader (ダウンロード処理)
        │     ├── gui.components (UIコンポーネント)
        │     ├── gui.constants  (定数)
        │     └── gui.styles     (スタイル)
        ├── gui.components
        │     └── gui.constants
        └── gui.styles
```

---

## 注意事項

- `gui_old.py` は旧実装であり、現在は使用されていません。将来的に削除予定。
- `__pycache__/` ディレクトリはPythonのバイトコードキャッシュであり、Gitで追跡不要（`.gitignore`推奨）。
- 仮想環境 `.venv/` はリポジトリに含めず、各環境で作成してください。















