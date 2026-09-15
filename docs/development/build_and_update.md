# ビルド・更新・配置

> 今回は既存のyt-dlpでビルド・配置・起動ログを確認しました。実通信と画面操作の確認範囲は [実施結果](organization_result.md) を参照してください。

プロジェクトのトップで実行します。

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
./scripts/update-and-install.sh
```

既定の配置先は `/Applications/YoutubeDownloader.app`。今後の更新も同じコマンドを使い、このアプリから起動してください。別の場所を使う場合は毎回同じ `--destination /absolute/path/YoutubeDownloader.app` を指定します。

## ビルドだけを検証する

```sh
./scripts/update-and-install.sh --skip-update --build-only
```

既存のbuild/distの成果物には上書きしません。OSの一時領域にPyInstallerのwork・dist・cacheを作り、新規成果物内の隠し属性を正常化し、cocoaプラグインの存在と署名を検証します。同期フォルダに.appを置くと拡張属性で署名が無効になることがあるため、保管用は `dist/releases/<日時>/YoutubeDownloader.app.tar.gz` とし、配置には一時領域の検証済み.appを使います。build-record.jsonに場所とバージョンを記録します。

一時領域はOSによって後日消される可能性があります。保管アーカイブは同期対象外の空フォルダで `tar -xzf /absolute/path/YoutubeDownloader.app.tar.gz` として展開できます。起動前に `codesign --verify --deep --strict /path/YoutubeDownloader.app` を確認してください。

## 失敗時と復旧

ビルド・署名が失敗すると配置しません。旧版がある場合は `dist/backups/<日時>/YoutubeDownloader.app` にコピーを検証して保管し、配置先と同じ親に作る `.YoutubeDownloader-stage-*` 内にもprevious.appとして保持します。配置処理が失敗したら旧版を戻します。旧版・失敗した出力は自動削除しません。

配置前に利用中のアプリを終了してください。署名検証と配置成功は起動・ダウンロードの成功を保証しません。新しい利用先からの操作確認が必要です。不具合時は新しいアプリを退避し、記録されたprevious.appを元の利用先へ戻します。上書きは避けてください。

.appはyt-dlpを自己更新できません。ソース版の起動時更新と混同せず、.appの更新には必ずビルドと配置を行います。

以前のルート版はdist/backups/pre-organization-root/へ保管済み。以前のdist版も保持し、実操作の確認が終わって不要になったら削除候補へ移します。実削除はユーザーが行います。
