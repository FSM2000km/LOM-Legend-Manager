# 活俠伝 伝説管理

活俠伝の「伝説」TXTを管理するBepInEx MODとデスクトップビューワです。

## 必要環境

- Windows 10またはWindows 11
- Steam版『活俠伝』
- BepInEx 6（Mono版）
- 対応する日本語化MOD

Pythonの別途インストールは不要です。BepInEx本体と日本語化MODはこのZIPに含まれません。

## 導入

ZIPの内容を『活俠伝』のゲームフォルダへ展開してください。`Mortal.exe`と同じ場所に`BepInEx`と`LegendViewer`が配置される構成です。

ゲームを起動するとMODが読み込まれます。ビューワは次のファイルから起動します。

```text
LegendViewer\Start-LegendViewer.cmd
```

## ビューワの配置

`LegendViewer.exe`はゲームフォルダ外へ移動しても動作します。デスクトップなど任意の場所へEXE単体を移動できます。プリセットはEXE内に格納され、伝説TXTとSQLiteはWindowsユーザーの次のフォルダから読み込みます。

```text
%USERPROFILE%\AppData\LocalLow\Obb Studio\Mortal
```

`Start-LegendViewer.cmd`を使用する場合は、EXEと同じフォルダへ一緒に移動してください。

## 保存データ

伝説TXT、SQLite、設定、ゲームのセーブデータは配布物に含まれません。MODの更新時もこれらを削除・上書きしません。

## アンインストール

ゲームを終了してから次を削除してください。

```text
BepInEx\plugins\LOM_LegendManager
LegendViewer
```

管理DBも削除する場合だけ、次を手動で削除してください。伝説TXTは`Legend`フォルダにあるため、DBを削除しても消えません。

```text
%USERPROFILE%\AppData\LocalLow\Obb Studio\Mortal\LegendManager
```
