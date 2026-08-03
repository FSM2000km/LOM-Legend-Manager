from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MANAGED_TAG_START = "【確定済みタグ】"
MANAGED_TAG_END = "【確定済みタグここまで】"
MANAGED_BLOCK_PATTERN = re.compile(
    r"\A【確定済みタグ】\r?\n[\s\S]*?\r?\n"
    r"【確定済みタグここまで】(?:\r?\n){1,2}"
)
RUBY_PATTERN = re.compile(r"[（(][ぁ-ゖァ-ヺー・]+[）)]")
WHITESPACE_PATTERN = re.compile(r"\s+")
EXPORT_TIMESTAMP_PATTERN = re.compile(r"LOM_Legend_(?P<timestamp>\d{14})", re.IGNORECASE)


@dataclass(frozen=True)
class LegendDocument:
    path: Path
    text: str
    body_text: str
    has_utf8_bom: bool
    newline: str
    content_sha256: str
    normalized_sha256: str
    file_sha256: str
    file_size: int


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_for_matching(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).replace("帮", "幇")
    normalized = RUBY_PATTERN.sub("", normalized)
    return WHITESPACE_PATTERN.sub(" ", normalized).strip()


def read_legend(path: Path) -> LegendDocument:
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text_bytes = raw[3:] if has_bom else raw
    text = text_bytes.decode("utf-8", errors="strict")
    body_text = MANAGED_BLOCK_PATTERN.sub("", text, count=1)
    normalized = normalize_for_matching(body_text)

    return LegendDocument(
        path=path,
        text=text,
        body_text=body_text,
        has_utf8_bom=has_bom,
        newline="\r\n" if "\r\n" in text else "\n",
        content_sha256=sha256_bytes(body_text.encode("utf-8")),
        normalized_sha256=sha256_bytes(normalized.encode("utf-8")),
        file_sha256=sha256_bytes(raw),
        file_size=len(raw),
    )


def build_managed_block(tags: Iterable[str], newline: str) -> str:
    unique_tags = list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
    return newline.join((MANAGED_TAG_START, *unique_tags, MANAGED_TAG_END, ""))


def embed_confirmed_tags(path: Path, tags: Iterable[str]) -> LegendDocument:
    document = read_legend(path)
    managed_block = build_managed_block(tags, document.newline)
    encoded = (managed_block + document.body_text).encode("utf-8")
    output = (b"\xef\xbb\xbf" + encoded) if document.has_utf8_bom else encoded

    original_stat = path.stat()
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(output)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)

        os.chmod(temporary_path, stat.S_IMODE(original_stat.st_mode))
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    updated = read_legend(path)
    if updated.content_sha256 != document.content_sha256:
        raise RuntimeError("管理ブロックの書き込みで本文ハッシュが変化しました。")
    return updated
