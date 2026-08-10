# ダウンロードの正確な仕組み（事実編）

この文書は、本リポジトリ内の実装（`downloader.py`, `gui.py`）を根拠として、ダウンロード処理の挙動を「事実」として整理します。推測は行いません。

- 対象: ダウンロード処理のデータフロー、`yt_dlp` オプション、再試行、進捗通知、出力ファイル命名
- 非対象: インストーラ、配布形態、OS固有の挙動（実装外）

---

## 1. 関係クラスと入力

- `downloader.DownloadRequest`
  - 事実: `url: str`, `output_dir: Path`, `quality: Optional[str]`（例: `"720p"`, `"1080p"` など）, `audio_only: bool`
  - 事実: `quality` は省略可能（`None` 可）。`__post_init__` で `output_dir` は `Path` 化。
- `gui.Application` 側の入力
  - 事実: 画面の既定値は `format=video`, `quality="1080p"`, 保存先はホーム配下の `Downloads`
  - 事実: 入力 URL は空チェックと `http` で始まることの簡易チェックを通過した場合のみダウンロード開始

---

## 2. 実行フロー（スレッド分離）

1. GUI（メインスレッド）で検証通過後、ワーカースレッドを起動
2. ワーカースレッドで `Downloader.download(request, progress_hooks=[Application._progress_hook])` を呼び出し
3. `Downloader.download()` 内処理（順序は実装どおり）
   - 出力ディレクトリの作成（`mkdir(parents=True, exist_ok=True)`）
   - `yt-dlp` の自動アップデート（初回のみ試行、詳細は 4 章）
   - `yt_dlp.YoutubeDL(オプション)` を生成して `download([url])` を実行
   - 例外時は警告ログを出しつつリトライ（詳細は 5 章）
4. `yt-dlp` の進捗フックが GUI の `_progress_hook` を呼び、GUI 側のイベントキューへ投入
5. GUI は 100ms 間隔でキューをポーリングし、進捗・完了・エラーを画面に反映

---

## 3. `yt_dlp` オプション（実装の事実）

`Downloader._build_options()` で構築される辞書（抜粋、キーは実装に準拠）:

- 共通
  - `outtmpl`: `%(title)s.mp4`（動画）/ `%(title)s.mp3`（音声のみ）
  - `noplaylist`: `True`（プレイリストは対象外）
  - `ignoreerrors`: `False`
  - `quiet`: `True`
  - `no_warnings`: `True`
  - `progress_hooks`: GUI から渡されたフック配列
  - `overwrites`: `False`（既存ファイルの上書きは行わない）
  - `prefer_ffmpeg`: `True`
- 音声のみ（`request.audio_only is True`）
  - `format`: `"bestaudio/best"`
  - `postprocessors`: `FFmpegExtractAudio`（`mp3`, `preferredquality="192"`）
  - `keepvideo`: `False`
- 動画（`request.audio_only is False`）
  - `format`: 品質選択ロジックの結果（4 章）
  - `merge_output_format`: `"mp4"`

---

## 4. 品質選択ロジック（動画時）

- 事実: `quality` が `None` の場合は `"bv*+ba/b"` を使用（`yt-dlp` の既定に近い包括的選択）
- 事実: `quality` が指定される場合は、以下の高さ（`height`）上限で選択
  - `"720p" → 720`, `"1080p" → 1080`, `"1440p" → 1440`, `"2160p" → 2160`, `"4320p" → 4320`
  - 上記以外の文字列が来た場合は既定値として `1080` を用いる
- 事実: 実際の `format` 文字列は  
  `bestvideo[height<=X]+bestaudio/b[height<=X]`

---

## 5. 再試行ポリシーと例外

- 事実: 既定最大リトライ回数は `3`（`Downloader(max_retries=3)` の既定）
- 事実: 失敗時は `WARNING` ログを残し、次回まで `min(5, attempt)` 秒スリープ（1回目:1秒, 2回目:2秒）
- 事実: 全試行失敗で `DownloadError` を送出（元例外を `__cause__` に連鎖）
- 事実: GUI 側は `DownloadError` を受け取り、エラーダイアログを表示し進捗をリセット

---

## 6. 進捗通知と完了通知

- 事実: 進捗通知は `yt-dlp` の `progress_hooks` から GUI の `_progress_hook(data: Dict[str, Any])` に渡る
- 事実: `data["status"] == "downloading"` のとき
  - 利用可能なら `total_bytes` か `total_bytes_estimate` と `downloaded_bytes` からパーセント算出
  - `eta`（秒）が正の数で来れば平滑化（移動平均）に使用
  - イベントキューへ `{type: "progress", progress: パーセント, status_message: 残り時間表示文字列}` を投入
- 事実: `data["status"] == "finished"` のとき
  - 即時の進捗 100% と整備中メッセージをイベントとして投入（ファイル名を含む場合あり）
- 事実: ダウンロード関数の正常終了後、GUI 側から `{type: "complete"}` イベントを別途投入し、完了ダイアログを表示

---

## 7. 自動アップデート（`yt-dlp -U`）

- 事実: `Downloader.download()` の先頭で、一度だけ自動アップデートを試行（`auto_update=True` かつ未更新時）
- 事実: 実際のコマンドは `sys.executable -m yt_dlp -U` を `subprocess.run(..., check=True)` で実行
- 事実: 成否にかかわらず以後の試行では同一プロセス内で再実行しない（フラグにより抑制）

---

## 8. 出力ファイル命名

- 事実: 動画は `%(title)s.mp4`、音声は `%(title)s.mp3`（`yt-dlp` のテンプレート展開に依存）
- 事実: 同名ファイルが存在する場合の上書きはしない（`overwrites=False`）

---

## 9. 既知の仕様（本実装から読み取れるもの）

- 事実: プレイリストは対象外（`noplaylist=True`）
- 事実: 動画時は `mp4` へマージ（`merge_output_format="mp4"`）
- 事実: 音声抽出は MP3 192kbps（`FFmpegExtractAudio` 設定）
- 事実: 進捗はポーリング（100ms）で GUI 表示が更新される

---

## 10. 未実装・不明点（推測なし）

- 事実: 字幕ダウンロード・サムネイル保存・メタデータ書き込みに関する `yt_dlp` オプション指定は、現行コードには存在しない
- 不明: 上記機能の将来対応方針（設計上の意図）はコードからは読み取れない

---

## 11. 参考ファイル

- 実行本体: `downloader.py`
- GUI/進捗・完了ハンドリング: `gui.py`

この文書は実装の追従性を重視しています。仕様変更時は当該実装箇所を更新し、本書の「事実」記述を合わせて改訂してください。






