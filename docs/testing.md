# テスト計画

## 手動テスト項目

### 起動
- `.venv` を作成後 `python main.py` でGUIが起動すること。
- FFmpeg を PATH から外した状態で起動し、警告ダイアログが表示されること。
- `.app` 版で同梱 yt-dlp が45日以上古い場合、エンジン更新を促す警告が出ること。

### URL入力
- 以下がすべて受け付けられること:
  `https://www.youtube.com/watch?v=...` / `https://youtu.be/...` /
  `https://m.youtube.com/watch?v=...` / `https://music.youtube.com/watch?v=...`
- `https://youtube.com.attacker.jp/...` のような偽装URLが拒否されること。
- 日本語を含むURL（%エンコード）を貼り付けると自動デコードされること。
- 「URLを一括追加」で複数行を投入でき、無効な行がスキップ件数として報告されること。

### キュー
- URLを追加した直後（タイトル取得中）に「ダウンロード開始」を押しても
  「全0件完了」にならず、取得完了後に自動でダウンロードが始まること。
- 50件以上を一括投入しても固まらないこと（タイトル取得は同時4件までに制限）。
- 失敗した項目に日本語の理由が表示され、マウスオーバーで全文が読めること。
- 「失敗を再試行」「完了をクリア」「すべてクリア」が期待通り動くこと。

### ダウンロード
- 動画（最高画質/2160p/1440p/1080p/720p）と音声（MP3各ビットレート/WAV）が保存できること。
- ダウンロード中に「全て停止」を押すと**即座に**停止し、再ダウンロードが走らないこと。
- 保存先を変更でき、完了ダイアログの「保存先を開く」が機能すること。
- 完了後 `~/Library/Logs/YoutubeDownloader/app.log` にログが追記されていること。

### 終了
- ダウンロード中にウィンドウを閉じてもクラッシュしないこと。

## 自動テストの状況

現時点で自動テストは未整備。以下は GUI 非依存で書けるため優先度が高い。

- **URL検証**: `UrlInputPanel._validate_youtube_url` / `_is_playlist_url` /
  `_is_channel_url` は純粋関数のため、そのままユニットテストできる。
- **エラー分類**: `downloader.is_permanent_error` / `describe_error` /
  `yt_dlp_age_days` も同様。
- **キュー制御**: `BatchDownloadManager` は `QCoreApplication` だけで動作する
  （QtWidgets 不要）。`Downloader.fetch_info` / `download` をスタブ化すれば、
  RESOLVING中の開始・並列上限・キャンセル挙動を検証できる。
  - スタブの引数は実装と揃えること（`download(self, request, progress_hooks=None,
    is_cancelled=None)`）。ずれるとテストだけが落ちて紛らわしい。
- **ダウンロード処理**: `yt_dlp.YoutubeDL.extract_info` を差し替えることで、
  リトライ回数（一時エラー3回 / 恒久エラー1回 / キャンセル1回）を検証できる。

### 補足: オフスクリーンGUIテストについて
`QT_QPA_PLATFORM=offscreen` は環境によっては Qt プラグインの初期化に失敗する。
ウィジェットを伴わないテストは `QCoreApplication` を使うこと。
