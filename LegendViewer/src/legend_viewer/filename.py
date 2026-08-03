from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path


RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
REPLACEMENTS = str.maketrans(
    {
        "\\": "￥",
        "/": "／",
        ":": "：",
        "*": "＊",
        "?": "？",
        '"': "”",
        "<": "＜",
        ">": "＞",
        "|": "｜",
        "\r": " ",
        "\n": " ",
        "\t": " ",
    }
)


def sanitize_component(value: str | None) -> str:
    source = unicodedata.normalize("NFC", value or "").translate(REPLACEMENTS)
    result = re.sub(
        r"\s+",
        " ",
        "".join(char for char in source if not unicodedata.category(char).startswith("C")),
    ).strip()
    result = result.rstrip(". ") or "不明"
    if result.upper() in RESERVED_NAMES:
        result += "_"
    return result


def build_target_path(
    directory: Path,
    file_prefix: str,
    title_name: str,
    heroine: str,
    exported_at: datetime,
    hash8: str,
    source_path: Path | None = None,
) -> Path:
    prefix = sanitize_component(file_prefix)
    title = sanitize_component(title_name)
    heroine_name = sanitize_component(heroine)
    timestamp = exported_at.strftime("%Y%m%d%H%M%S")

    def make_name(suffix: str = "") -> str:
        return f"{prefix}_{title}_{heroine_name}_{timestamp}_{hash8}{suffix}.txt"

    while len(str(directory / make_name())) > 240 and len(title) > 8:
        title = title[:-1]

    candidate = directory / make_name()
    if source_path and candidate.resolve() == source_path.resolve():
        return candidate
    if not candidate.exists():
        return candidate

    for number in range(2, 10000):
        candidate = directory / make_name(f"_{number}")
        if not candidate.exists():
            return candidate
    raise FileExistsError("リネーム先の空きファイル名を確保できませんでした。")
