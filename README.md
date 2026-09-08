# YouTube Downloader for macOS

YouTubeの動画やプレイリスト、チャンネルからコンテンツを高品質かつ一括でダウンロードするためのmacOS向けデスクトップアプリケーションです。

## 概要
macOSのネイティブ体験を重視し、PySide6 (Qt) で構築された高機能ダウンローダーです。単一の動画だけでなく、膨大なプレイリストやチャンネル全体の動画をバックグラウンドで並列処理し、効率的にローカル保存することに特化しています。

## 主な機能
- **洗練されたUI/UX**: 
    - macOS Ventura以降に最適化されたダークモードデザイン。
    - スムーズなプログレスバーのアニメーションと、リアルタイムなステータスフィードバック。
- **一括処理 (Batch Management)**: 
    - 複数のURLをキューに積み、最大並列数（デフォルト2）を維持しながら効率的に処理。
    - プレイリストURLの自動展開、およびチャンネルURLからの動画一覧スキャンに対応。
- **高品質・多彩なフォーマット**: 
    - **動画**: 最高画質（自動）、2160p, 1440p, 1080p, 720p の選択が可能（MP4形式）。
    - **音声**: MP3 (320/256/192/128kbps) および WAV 形式への変換。
- **インテリジェントなURL処理**: 
    - `www` / `m` (モバイル) / `music` の各サブドメインに対応。
    - 日本語などの非英数文字を含むURLをペーストした際、ブラウザによるエンコード（%記号の羅列）を検知し、自動的に元の日本語に戻して表示。
- **エンジンの更新**: 
    - ソースから起動した場合、起動時に `yt-dlp` の更新をバックグラウンドで確認します。
    - **`.app` 版は自己更新できません**（yt-dlp がアプリ内に固められているため）。エンジンが古くなると起動時に警告が出るので、[エンジンの更新](#エンジンの更新) の手順で再ビルドしてください。

## 前提条件
- **OS**: macOS Ventura 13.0 以降 (Apple Silicon / Intel 両対応)
- **依存ツール**: Python 3.12系 および FFmpeg が必要です。未導入の場合はHomebrewでインストールしてください：
  ```bash
  brew install python@3.12 ffmpeg
  ```

## セットアップ
1. リポジトリを適切な場所に配置し、仮想環境を作成・有効化します：
   ```bash
   cd /Users/jun/Desktop/YoutubeDownloader
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```
2. 必要なパッケージを一括インストールします：
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

## 利用方法
### 起動方法
- **アプリとして起動 (推奨)**: `YoutubeDownloader.app` をダブルクリックします。
- **ターミナル起動 (開発時)**:
  ```bash
  source .venv/bin/activate
  python main.py
  ```

### 操作ガイド
1. **URLの追加**:
    - メインの入力欄にURLを貼り付けて `⏎` を押すとキューに追加されます。
    - 「URLを一括追加」ボタンから、複数のURLを1行ずつまとめて流し込むことが可能です。
    - チャンネル全体の動画を保存したい場合は、チャンネルURLを入力して「チャンネルから取得」を押してください。
2. **フォーマット設定**:
    - 保存形式（動画/音声）と、目的の解像度またはビットレートを選択します。
3. **保存先の確認**:
    - デフォルトは `Downloads` フォルダです。必要に応じて「変更」ボタンから指定してください。
4. **ダウンロードの実行**:
    - 「ダウンロード開始」ボタン、またはショートカットキー `⌘ + ⏎ (Cmd + Return)` で処理を開始します。
    - ダウンロード中は「全て停止」ボタンでいつでも中断可能です。

### ログとメンテナンス
- アプリケーションの動作ログは以下に出力されます。問題が発生した際はこちらを確認してください：
  `~/Library/Logs/YoutubeDownloader/app.log`

## エンジンの更新

`yt-dlp` は YouTube の仕様変更に追随するため頻繁に更新されます。**古いままだと全ての
ダウンロードが `HTTP Error 403: Forbidden` で失敗します。** `.app` 版はエンジンを
自己更新できないため、その場合は更新して再ビルドしてください。

```bash
.venv/bin/pip install --upgrade yt-dlp
.venv/bin/pyinstaller YoutubeDownloader.spec --noconfirm
```

ビルドした `.app` は `dist/` に出力されます。`/Applications` などに配置している場合は、
そちらも差し替えてください。

> **注意**: プロジェクトが iCloud 同期対象のフォルダ（デスクトップ・書類など）にある場合、
> ファイルプロバイダが付与する拡張属性により `codesign` が
> 「resource fork, Finder information, or similar detritus not allowed」で失敗します。
> その場合は同期対象外の場所へコピーしてから署名し、それを配置してください：
> ```bash
> ditto --norsrc --noextattr --noacl dist/YoutubeDownloader.app /tmp/YoutubeDownloader.app
> codesign -s - --force --all-architectures --deep /tmp/YoutubeDownloader.app
> ```

## トラブルシューティング
- **`403 Forbidden` で失敗する / 全ての動画が落とせない**: エンジンが古いのが原因です。
  [エンジンの更新](#エンジンの更新) を実行してください。最も頻度の高い不具合です。
- **インストールが止まる**: インターネット接続を確認し、`pip install` を再度実行してください。
- **音声変換ができない**: FFmpegがパスに通っているか確認してください（`ffmpeg -version` がターミナルで動く必要があります）。未検出の場合は起動時に警告が出ます。
- **特定の動画だけ落とせない**: 削除済み・非公開・メンバー限定・地域制限などの可能性があります。
  キューの該当項目に理由が表示されます（全文はマウスオーバーで確認できます）。

## 開発・設計資料
- **ユーザーマニュアル**: 操作方法の詳細は [docs/USER_MANUAL.md](docs/USER_MANUAL.md) を参照してください。
- **テスト**: [docs/testing.md](docs/testing.md) に手動テスト項目と自動テスト方針をまとめています。
- **UIスタディ**: プログレスバーのアニメーションや設計思想については [docs/progress_bar_animation_study.md](docs/progress_bar_animation_study.md) を参照してください。

---
*旧バージョンのREADME（Tkinter版等）は [README_LEGACY.md](README_LEGACY.md) として保管されています。*
