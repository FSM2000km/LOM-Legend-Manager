from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModSettingDefinition:
    section: str
    key: str
    label: str
    kind: str
    default: object
    description: str
    minimum: int = 0
    maximum: int = 0
    choices: tuple[tuple[str, str], ...] = ()


MOD_SETTINGS = (
    ModSettingDefinition("General", "Enabled", "MODを有効にする", "bool", True, "伝説の監視と管理を有効にします。"),
    ModSettingDefinition("General", "RenameFiles", "ファイル名を変更する", "bool", True, "ED名と結縁相手を使って新規TXTを命名します。"),
    ModSettingDefinition("General", "ProcessExistingFiles", "既存TXTを登録する", "bool", False, "起動時に未処理の時刻名TXTを登録します。"),
    ModSettingDefinition("General", "MatchExistingFiles", "既存TXTを照合する", "bool", True, "保存済み伝説と既存TXTを完全一致で照合します。"),
    ModSettingDefinition("General", "ExistingSlotScanLimit", "照合スロット上限", "int", 200, "照合対象として確認するスロット番号の上限です。", 1, 10000),
    ModSettingDefinition("General", "DebounceMilliseconds", "書き込み待機時間", "int", 750, "ファイル書き込み完了を待つ時間です。", 250, 10000),
    ModSettingDefinition(
        "Export",
        "AutoExportTiming",
        "自動エクスポート時機",
        "choice",
        "EndingDisplayed",
        "TXTとViewer用データを自動出力する時機です。",
        choices=(
            ("LegendSaved", "書庫への保存時"),
            ("EndingDisplayed", "ED画面の表示時"),
            ("Disabled", "自動エクスポートしない"),
        ),
    ),
    ModSettingDefinition("Export", "ShowManualExportFileName", "手動出力のファイル名を表示", "bool", True, "手動エクスポート完了画面に最終ファイル名を表示します。"),
    ModSettingDefinition("Export", "ShowAutoExportFileName", "自動出力の通知を表示", "bool", True, "自動エクスポート時に最終ファイル名を一時表示します。"),
)


SECTION_PATTERN = re.compile(r"^\s*\[([^]]+)]\s*$")
KEY_PATTERN = re.compile(r"^(?P<prefix>\s*)(?P<key>[^#;=]+?)(?P<spacing>\s*=\s*)(?P<value>.*?)(?P<suffix>\s*)$")


def read_mod_settings(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8-sig")
    raw_values: dict[tuple[str, str], str] = {}
    section = ""
    for line in text.splitlines():
        section_match = SECTION_PATTERN.match(line)
        if section_match:
            section = section_match.group(1)
            continue
        key_match = KEY_PATTERN.match(line)
        if key_match:
            raw_values[(section, key_match.group("key").strip())] = key_match.group("value").strip()

    result: dict[str, object] = {}
    for definition in MOD_SETTINGS:
        raw = raw_values.get((definition.section, definition.key))
        if raw is None:
            result[definition.key] = definition.default
        elif definition.kind == "bool":
            result[definition.key] = raw.casefold() == "true"
        elif definition.kind == "int":
            try:
                result[definition.key] = max(definition.minimum, min(definition.maximum, int(raw)))
            except ValueError:
                result[definition.key] = definition.default
        else:
            allowed = {value for value, _ in definition.choices}
            result[definition.key] = raw if raw in allowed else definition.default
    if ("Export", "AutoExportTiming") not in raw_values:
        legacy = raw_values.get(("Export", "AutoExportOnSave"))
        if legacy is not None and legacy.casefold() == "false":
            result["AutoExportTiming"] = "Disabled"
    return result


def write_mod_settings(path: Path, values: dict[str, object]) -> Path:
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw[3:].decode("utf-8") if has_bom else raw.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()

    for definition in MOD_SETTINGS:
        rendered = _render_value(definition, values.get(definition.key, definition.default))
        section_start, section_end = _find_section(lines, definition.section)
        if section_start is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend((f"[{definition.section}]", f"{definition.key} = {rendered}"))
            continue
        replaced = False
        for index in range(section_start + 1, section_end):
            match = KEY_PATTERN.match(lines[index])
            if match and match.group("key").strip() == definition.key:
                lines[index] = f"{match.group('prefix')}{definition.key}{match.group('spacing')}{rendered}{match.group('suffix')}"
                replaced = True
                break
        if not replaced:
            lines.insert(section_end, f"{definition.key} = {rendered}")

    output = (newline.join(lines) + newline).encode("utf-8")
    if has_bom:
        output = b"\xef\xbb\xbf" + output
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as temporary:
            temporary.write(output)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return backup


def _find_section(lines: list[str], section: str) -> tuple[int | None, int]:
    start: int | None = None
    for index, line in enumerate(lines):
        match = SECTION_PATTERN.match(line)
        if match and start is not None:
            return start, index
        if match and match.group(1) == section:
            start = index
    return (start, len(lines))


def _render_value(definition: ModSettingDefinition, value: object) -> str:
    if definition.kind == "bool":
        return "true" if bool(value) else "false"
    if definition.kind == "int":
        return str(max(definition.minimum, min(definition.maximum, int(value))))
    allowed = {choice for choice, _ in definition.choices}
    return str(value) if str(value) in allowed else str(definition.default)


def is_game_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Mortal.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return '"Mortal.exe"' in result.stdout
