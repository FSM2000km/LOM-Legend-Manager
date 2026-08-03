# LOM Legend Manager

『活俠伝（Legend of Mortal）』が出力する「伝説」TXTを整理する、BepInEx MODとWindowsデスクトップビューワです。

MODが新しい伝説のエクスポートを監視し、確定できたED名と結縁相手でファイルを命名します。ビューワでは、既存ファイルを含む伝説の検索、タグ付け、メモ、重複確認、手動補正を行えます。

本プロジェクトは非公式ツールです。ゲーム本体、BepInEx、日本語化MODは配布物に含まれません。

## 構成

| コンポーネント | 役割 |
| --- | --- |
| LOM Legend Manager MOD | ゲーム内情報と伝説エクスポートを監視し、ファイルを命名して確定情報を出力します。 |
| Legend Viewer | 伝説TXTとMODの出力をSQLiteへ取り込み、一覧表示、検索、タグ編集などを行います。 |

MODはSQLiteを直接操作しません。MODがJSONイベントを受信箱へ原子的に書き出し、ViewerだけがSQLiteを更新します。

## ダウンロード

[GitHub Releases](https://github.com/FSM2000km/LOM-Legend-Manager/releases)から最新版の`LOM_LegendManager_v*.zip`をダウンロードしてください。

## 必要環境

- Windows 10またはWindows 11
- Steam版『活俠伝』
- BepInEx 6（Mono版）
- 対応する日本語化MOD

配布版Viewerには必要なPythonランタイムが含まれるため、Pythonを別途インストールする必要はありません。

## 導入

1. ゲームを終了します。
2. 配布ZIPの内容を『活俠伝』のゲームフォルダへ展開します。
3. `Mortal.exe`と同じ階層に`BepInEx`と`LegendViewer`があることを確認します。
4. ゲームを起動します。BepInExからMODが読み込まれます。
5. `LegendViewer\Start-LegendViewer.cmd`を起動します。

配置後の主要ファイルは次のとおりです。

```text
LegendOfMortal\
├─ Mortal.exe
├─ BepInEx\
│  └─ plugins\LOM_LegendManager\
│     ├─ LegendManager.Plugin.dll
│     └─ data\
└─ LegendViewer\
   ├─ LegendViewer.exe
   └─ Start-LegendViewer.cmd
```

`LegendViewer.exe`はゲームフォルダ外へ移動しても動作します。`Start-LegendViewer.cmd`を使う場合は、EXEと同じフォルダへ一緒に移動してください。

## ファイル名

ED名と結縁相手を確定できた場合は、次の形式で命名します。

```text
ED48_武林（ぶりん）伝説_小師妹_20260723013650_35c24603.txt
```

確定できない情報は推測せず、`ED名不明`または`結縁相手不明`とします。`無結縁`は、無結縁であることが明確なEDにだけ使用します。

同名ファイルが存在する場合は`_2`以降を付け、既存ファイルを削除しません。リネームだけでは伝説本文を変更しません。

## 判定方針

- EDはゲーム内ED ID、または保存済み伝説と本文全体のSHA-256が一致した場合に確定します。
- 結縁相手は、結縁成立を示す観測済みStory keyから確定します。
- ゲーム内の想い人IDや、EDごとに想定される人物だけから結縁を推測しません。
- 手動で確定したED名、結縁相手、タグは、後の自動走査で上書きしません。
- 現在の対象はEDの伝説です。死亡記録の独自エクスポートには未対応です。

## Viewerの機能

- 伝説TXTの一覧表示と全文検索
- ED名、結縁相手、タグ、メモによる管理
- ED名と結縁相手を使った手動リネーム
- 本文ハッシュによる重複検出
- SQLite DBのバックアップ
- 確定済みタグの伝説TXT文頭への追記
- MOD受信箱と伝説フォルダの自動監視

タグの文頭追記は専用の管理ブロックを置換するため、同じタグを重複して追加しません。外部アプリでTXTが変更された場合は誤上書きを防ぐため処理を拒否するので、Viewerで再読込してから実行してください。

## タグとネタバレ

生存、唐門加入、金烏討伐成功など、実際に観測できた情報は通常の候補として表示します。別ルートの存在を示唆し得る候補は、`ネタバレタグを追加`を押すまで表示しません。

自由タグも追加できます。自動タグは、日本語化MOD JP v2.4から抽出したプリセットと、伝説に実際に記録されたStory keyだけを参照します。

タグ定義の詳細は[LegendManager/TAGS.md](LegendManager/TAGS.md)を参照してください。

## 既存の伝説

Viewerは既存の`LOM_Legend_*.txt`も初回走査でDBへ登録しますが、自動ではリネームしません。

MODを導入した状態でゲーム内の保存済み伝説を確認できる場合は、再生成した本文と既存TXTのSHA-256が完全一致したEDだけを確定します。完全一致しないファイルや、結縁成立Story keyを持たない旧ファイルは未確定のまま残り、Viewerから手動補正できます。

## 保存場所

```text
伝説TXT:
%USERPROFILE%\AppData\LocalLow\Obb Studio\Mortal\Legend

SQLite DB:
%USERPROFILE%\AppData\LocalLow\Obb Studio\Mortal\LegendManager\legend_manager.db

MODイベント受信箱:
%USERPROFILE%\AppData\LocalLow\Obb Studio\Mortal\LegendManager\inbox
```

伝説TXT、SQLite、設定、ゲームのセーブデータは配布ZIPに含まれません。MODやViewerを更新しても、これらを削除または上書きしません。

## MOD設定

初回起動後、`BepInEx\config\lom.jp.legendmanager.cfg`が生成されます。

| 設定 | 初期値 | 内容 |
| --- | --- | --- |
| `Enabled` | `true` | MODを有効にします。 |
| `RenameFiles` | `true` | 新しくエクスポートされた伝説を命名します。 |
| `ProcessExistingFiles` | `false` | 起動時に未処理の時刻名ファイルを登録するか指定します。既存ファイルは自動リネームしません。 |
| `MatchExistingFiles` | `true` | 既存TXTと保存済み伝説を完全一致で照合します。 |
| `ExistingSlotScanLimit` | `200` | 確認する保存済み伝説スロット番号の上限です。 |
| `DebounceMilliseconds` | `750` | ファイルへの書き込み完了を待つ時間です。 |

## アンインストール

ゲームを終了してから次を削除します。

```text
BepInEx\plugins\LOM_LegendManager
LegendViewer
```

管理DBも削除する場合だけ、次のフォルダを手動で削除してください。伝説TXTは別の`Legend`フォルダにあるため、DBを削除しても消えません。

```text
%USERPROFILE%\AppData\LocalLow\Obb Studio\Mortal\LegendManager
```

## 開発

ソースからViewerを実行する場合はPython 3.11以降が必要です。セットアップスクリプトは依存関係を`LegendViewer\.venv`へ導入します。

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\LegendViewer\Setup-LegendViewer.ps1
```

テストは次のコマンドで実行します。

```powershell
Push-Location .\LegendViewer
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Pop-Location
```

配布ZIPはVisual Studio Build Tools 2022と導入済みのゲーム環境を使用して作成します。ゲームが既定場所以外にある場合は、`LOM_GAME_ROOT`を設定してください。

```powershell
$env:LOM_GAME_ROOT = 'D:\SteamLibrary\steamapps\common\LegendOfMortal'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\LegendManager\tools\Build-Release.ps1 -Version 0.1.2
```

ビルド時には、配布物へローカルのユーザーディレクトリやリポジトリ絶対パスが混入していないか検査します。

## ディレクトリ

```text
LegendManager/      BepInEx MOD、プリセット、タグ定義、配布スクリプト
LegendViewer/       PySide6 Viewer、SQLite管理、テスト
LegendManagerMock/  要件定義、作業規約、UIモック
```
