# 活俠伝 伝説管理ビューワ

ローカルHTTPサーバーを使わないPySide6デスクトップアプリです。伝説TXTとMOD受信箱を読み込み、一覧、全文検索、タグ、メモ、重複、手動補正をSQLiteで管理します。

## 起動

通常は`Start-LegendViewer.cmd`をダブルクリックします。`LegendViewer.exe`があればEXEを優先し、なければ`.venv`のPythonを使います。

配布版の`LegendViewer.exe`には日本語プリセットが内蔵されています。EXEはデスクトップなど任意のフォルダへ単独で移動しても動作し、伝説TXTとDBは`LocalLow\Obb Studio\Mortal`から読み込みます。

VS Codeではワークスペース直下を開き、実行構成`Legend Viewer`を選択します。テストはタスク`Legend Viewer: Test`から実行できます。

## 初回セットアップ

配布EXEを使わない場合だけ、PowerShellで次を実行します。

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\Setup-LegendViewer.ps1
```

PySide6は`LegendViewer\.venv`だけに導入され、システムPythonは変更しません。

## 保存場所

```text
伝説TXT:
%USERPROFILE%\AppData\LocalLow\Obb Studio\Mortal\Legend

SQLite:
%USERPROFILE%\AppData\LocalLow\Obb Studio\Mortal\LegendManager\legend_manager.db

MODイベント:
%USERPROFILE%\AppData\LocalLow\Obb Studio\Mortal\LegendManager\inbox
```

DBのバックアップはアプリ上部の`DBをバックアップ`から作成できます。

## 操作

- `再読込`: MOD受信箱を取り込み、伝説フォルダを再走査します。起動中は3秒間隔で変更も監視します。
- `確定情報を保存`: ED名と結縁相手を手動確定します。`唐嬌嬌`も選択できます。手動値は後の自動走査で上書きしません。
- `ED名と結縁相手でリネーム`: 確定情報から安全なファイル名を作ります。衝突時は`_2`以降を付け、既存ファイルを削除しません。
- `タグ`: 生存、唐門加入、金烏討伐成功は通常候補に表示します。観測済みであっても別ルートを示唆し得る候補は`ネタバレタグを追加`を押すまで表示しません。
- `確定済みのタグを文頭に追記`: 確定タグをTXTへ直接書きます。同じ管理ブロックを置換するため重複せず、本文ハッシュは変わりません。

外部アプリで本文が変更された後は、誤上書きを防ぐためタグ追記を拒否します。`再読込`して内容を確認してから再実行してください。

## 既存ファイル

既存TXTは初回にDBへ登録し、自動リネームしません。MOD起動時に保存済み伝説スロットから再生成した本文とSHA-256が完全一致した場合だけEDを確定します。結縁相手は成立済みStory keyと完全一致した場合だけ自動確定し、該当しなければ`結縁相手不明`として扱います。Story keyを持たない旧ファイルでは、ファイル名に明記された相手を低優先度情報として維持します。

## コマンド

```powershell
# UIを開かず同期
.\.venv\Scripts\python.exe -m legend_viewer --sync-only

# テスト
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

初期版はEDだけを対象にします。死亡記録の独自エクスポートは将来拡張です。
