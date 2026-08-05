# LOM Legend Manager

『活俠傳（Legend of Mortal）』が出力する「伝説」TXTを整理する、BepInEx MODとWindowsデスクトップビューワです。

MODが新しい伝説のエクスポートを監視し、確定できたED名と結縁相手でファイルを命名します。ビューワでは、既存ファイルを含む伝説の検索、タグ付け、メモ、重複確認、手動補正を行えます。

本プロジェクトは非公式ツールです。BepInExと日本語化MODは配布物に含まれません。

## 既知の不具合・仕様

- 現在、ED名や各種フラグは、MODがゲーム実行中に観測した情報をViewerへ渡し、外部SQLiteに保存する方式です。そのため、MOD導入前に作成された既存の伝説をあとからエクスポートしても、ED名を正しく取得できない場合があります。動作確認・利用は、MOD導入後に新しく迎えたEDの伝説をエクスポートして行ってください。
- **不自然な挙動や、追加してほしいタグがあったらお気軽にIssues/X/Discordなどへの記載をしていただけると嬉しいです。**


保存時パラメータとED画像も、バージョン0.2.0以降のMODが回収したものだけを表示します。既存TXTだけから過去の能力値や画像を推測しません。ED画像は保存時に素材画像を回収し、ゲーム内の伝説一覧でその伝説を開いたときは本の背景を含む表示画像へ更新します。

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
- Steam版『活俠傳』
- BepInEx 6（Mono版）
- 対応する日本語化MOD

配布版Viewerには必要なPythonランタイムが含まれるため、Pythonを別途インストールする必要はありません。

## 導入

1. ゲームを終了します。
2. 配布ZIP内の`BepInEx`フォルダを『活俠傳』のゲームフォルダへ展開します。
3. `Mortal.exe`と同じ階層に`BepInEx`があることを確認します。
4. `LegendViewer`フォルダはゲームフォルダ内に置く必要はありません。展開後はデスクトップなど任意の場所へ移動できます。
5. ゲームを起動します。BepInExからMODが読み込まれます。
6. `LegendViewer\Start-LegendViewer.cmd`または`LegendViewer.exe`を起動します。CMDを使う場合は、EXEと同じフォルダに置いてください。

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

同名ファイルが存在する場合は`_2`以降を付け、既存ファイルを削除しません。リネームだけでは伝説本文を変更しません。

## Viewerの機能

- 伝説TXTの一覧表示と全文検索
- ED・結縁相手・既知タグ・人物傾向による複数選択フィルターと、一覧列による昇順・降順ソート
- 性情・処世・品性・道徳を分けた人物傾向の一覧表示。数値は隠し、各列の幅はドラッグで変更・保存できます。
- ED名、結縁相手、タグ、メモによる管理
- 選択中の本文内検索、件数表示、前後ジャンプ
- ED名・結縁相手を除く確定タグの本文上部表示
- ED名と結縁相手を使った手動リネーム
- 本文ハッシュによる重複検出
- SQLite DBのバックアップ
- ED・結縁相手、確定済みタグ、各種保存時パラメータから大カテゴリを選ぶTXT文頭への確定情報追記
- MOD受信箱と伝説フォルダの自動監視
- 本文フォント、文字サイズ、ルビ表示方法の変更
- EDごとに回収したED画像の表示
- 保存時点の能力、性情・処世・品性・道徳、所持金、名声、団結、好感度、スキルレベルの階層表示
- 左右サイドバーの個別表示切替
- ゲーム本体の場所と、伝説TXT・ED画像の保存先の指定
- 伝説ごとの本文スクロール位置と最後に開いた伝説の復元
- ViewerからのLOM Legend Manager MOD設定編集

確定情報の文頭追記は専用の管理ブロックを置換するため、同じ情報を重複して追加しません。外部アプリでTXTが変更された場合は誤上書きを防ぐため処理を拒否するので、Viewerで再読込してから実行してください。

## タグとネタバレ

生存、唐門加入、金烏上人死亡など、実際に観測できた情報は通常の候補として表示します。別ルートの存在を示唆し得る候補は、`ネタバレタグを追加`を押すまで表示しません。

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

共有パス設定:
%USERPROFILE%\AppData\LocalLow\Obb Studio\Mortal\LegendManager\settings.json
```

Viewerの`パス設定`では、`ゲーム本体の場所`は既存の`Mortal.exe`とBepInExを探す場所だけを指定します。`伝説TXT・ED画像の保存先`はMODのエクスポート先を上書きします。保存先変更時に既存TXTや`Pictures`は移動しません。指定先が一時的に使えない場合、MODは設定を保持したまま標準の`Legend`フォルダへ保存します。

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
| `AutoExportTiming` | `LegendSaved` | 自動エクスポート時機を`LegendSaved`（書庫保存時）、`EndingDisplayed`（ED画面表示時）、`Disabled`（無効）から選びます。 |
| `ShowManualExportFileName` | `true` | 手動エクスポート時に最終ファイル名を表示します。 |
| `ShowAutoExportFileName` | `true` | 自動エクスポート時に最終ファイル名を一時表示します。 |

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

## ディレクトリ

```text
LegendManager/      BepInEx MOD、プリセット、タグ定義、配布スクリプト
LegendViewer/       PySide6 Viewer、SQLite管理、テスト
```

## ライセンス

このプロジェクトは[MIT License](LICENSE)で公開しています。

何をしても構いませんし、何もしなくても構いません。
