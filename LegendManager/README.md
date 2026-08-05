# LOM Legend Manager MOD

活俠傳のED「伝説」エクスポートを監視するBepInEx 6プラグインです。ゲーム内のED ID、伝説スロット、観測済みStory keyを取得し、日本語化MOD JP v2.4準拠の名前でTXTをリネームします。人物欄にはゲームの想い人IDではなく、結縁成立を明記するStory keyから確定した相手を使用します。

## 動作

新しい伝説をエクスポートすると、通常は次の形式になります。

```text
ED48_武林（ぶりん）伝説_小師妹_20260723013650_35c24603.txt
```

EDを解決できない場合は推測せず、次の形式にします。

```text
ED名不明_結縁相手不明_20260723013650_35c24603.txt
```

MODはSQLiteへ接続しません。確定情報をJSONイベントとして次へ原子的に出力し、PythonビューワだけがSQLiteを更新します。

初期設定では伝説保存時にTXTを自動エクスポートします。同じスロット・同じ本文をあとから手動エクスポートした場合は二重出力せず、既存の最終ファイル名を表示します。保存時点の能力値、性情・処世・品性・道徳の数値と段階名、遭遇済み人物の好感度、取得済みスキルとレベルもJSONイベントへ保存します。

ED画像は伝説のエクスポート時に素材画像を回収します。ゲーム内の伝説一覧でその伝説を開くと、画面に表示された本の背景込みの画像を同じEDへ登録し直します。画面取得に失敗した場合も、先に回収した素材画像は維持します。

```text
%USERPROFILE%\AppData\LocalLow\Obb Studio\Mortal\LegendManager\inbox
```

## 配置

実行ファイルとプリセットの配置先は次の通りです。

```text
BepInEx\plugins\LOM_LegendManager\LegendManager.Plugin.dll
BepInEx\plugins\LOM_LegendManager\data\jp_v2_4_presets.json
BepInEx\plugins\LOM_LegendManager\data\tags_catalog.json
```

初回起動後、設定は`BepInEx\config\lom.jp.legendmanager.cfg`に生成されます。

- `Enabled=true`: MODを有効にします。
- `RenameFiles=true`: 新規エクスポートをリネームします。
- `ProcessExistingFiles=false`: 既存の時刻名ファイルを登録しません。既存ファイルは自動リネームしません。
- `MatchExistingFiles=true`: 既存TXTの本文を保存済み伝説スロットと照合し、完全一致したEDだけを確定します。
- `ExistingSlotScanLimit=200`: 照合対象として確認する伝説スロット番号の上限です。
- `DebounceMilliseconds=750`: ファイル監視時の安定化待ちです。
- `AutoExportTiming=EndingDisplayed`: 自動エクスポート時機です。`LegendSaved`（書庫保存時）、`EndingDisplayed`（ED画面表示時）、`Disabled`（無効）から選べます。
- `ShowManualExportFileName=true`: 手動エクスポート時に最終ファイル名を表示します。
- `ShowAutoExportFileName=true`: 自動エクスポート時にファイル名を一時表示します。

## 制約

- 初期版はEDの伝説だけを対象にします。死亡記録の独自エクスポートは含みません。
- 結縁成立を示すStory keyがなければ、想い人IDやED固有の想い人から推測せず`結縁相手不明`とします。
- `無結縁`は無結縁が明確なEDだけに使用します。ビューワで手動確定した値は自動判定より優先されます。
- 既存TXTの照合では本文全体のSHA-256が保存スロットから再生成した本文と一致した場合だけ確定します。
- 照合による既存ファイルのリネームは行いません。完全一致しないファイルは未確定のまま残します。
- 本文はリネーム時に変更しません。
- 日本語化MODの実行時DLLや用語集には依存せず、抽出済みJP v2.4プリセットだけを参照します。能力名とスキル名は保存時のゲーム内ローカライズ結果を記録します。

完全なタグ一覧は[TAGS.md](TAGS.md)を参照してください。
