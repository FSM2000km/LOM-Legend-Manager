from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage


RUBY_PATTERN = re.compile(
    r"(?P<base>[\u3400-\u9fff々〆ヵヶ]+)[（(]"
    r"(?P<reading>[ぁ-ゖァ-ヺー・]+)[）)]"
)
RUBY_MODE = "ruby"
IGNORE_MODE = "ignore"
HOVER_MODE = "hover"
RUBY_MODES = (RUBY_MODE, IGNORE_MODE, HOVER_MODE)


@dataclass(frozen=True)
class ReaderSettings:
    font_family: str = "Yu Gothic UI"
    font_size: int = 16
    ruby_mode: str = RUBY_MODE


class ReaderSettingsStore:
    def __init__(self, path: Path) -> None:
        self.settings = QSettings(str(path), QSettings.Format.IniFormat)

    def load(self) -> ReaderSettings:
        font_family = str(self.settings.value("reader/font_family", "Yu Gothic UI"))
        font_size = max(8, min(48, int(self.settings.value("reader/font_size", 16))))
        ruby_mode = str(self.settings.value("reader/ruby_mode", RUBY_MODE))
        if ruby_mode not in RUBY_MODES:
            ruby_mode = RUBY_MODE
        return ReaderSettings(font_family, font_size, ruby_mode)

    def save(self, value: ReaderSettings) -> None:
        self.settings.setValue("reader/font_family", value.font_family)
        self.settings.setValue("reader/font_size", value.font_size)
        self.settings.setValue("reader/ruby_mode", value.ruby_mode)
        self.settings.sync()

    def load_last_legend_id(self) -> int | None:
        value = self.settings.value("reader/last_legend_id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def save_last_legend_id(self, legend_id: int) -> None:
        self.settings.setValue("reader/last_legend_id", legend_id)
        self.settings.sync()

    def load_position(self, legend_id: int, content_sha256: str) -> float:
        prefix = f"reader_positions/{legend_id}"
        if self.settings.value(f"{prefix}/content_sha256", "") != content_sha256:
            return 0.0
        try:
            return max(0.0, min(1.0, float(self.settings.value(f"{prefix}/ratio", 0.0))))
        except (TypeError, ValueError):
            return 0.0

    def save_position(self, legend_id: int, content_sha256: str, ratio: float) -> None:
        prefix = f"reader_positions/{legend_id}"
        self.settings.setValue(f"{prefix}/content_sha256", content_sha256)
        self.settings.setValue(f"{prefix}/ratio", max(0.0, min(1.0, ratio)))

    def load_embed_categories(self, defaults: set[str]) -> set[str]:
        value = self.settings.value("embed/categories")
        if value is None:
            return set(defaults)
        if isinstance(value, str):
            values = value.split(",")
        else:
            values = list(value)
        return {str(item) for item in values if str(item)}

    def save_embed_categories(self, categories: set[str]) -> None:
        self.settings.setValue("embed/categories", sorted(categories))
        self.settings.sync()

    def load_legend_column_widths(self, column_count: int) -> list[int] | None:
        value = self.settings.value("library/column_widths")
        if value is None:
            return None
        values = value.split(",") if isinstance(value, str) else list(value)
        try:
            widths = [int(item) for item in values]
        except (TypeError, ValueError):
            return None
        if len(widths) != column_count or any(width < 24 for width in widths):
            return None
        return widths

    def save_legend_column_widths(self, widths: list[int]) -> None:
        self.settings.setValue("library/column_widths", widths)
        self.settings.sync()


class LocalReaderPage(QWebEnginePage):
    def acceptNavigationRequest(
        self,
        url: QUrl,
        navigation_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        del navigation_type, is_main_frame
        return url.scheme() in ("about", "data")


def render_reader_body_html(text: str, settings: ReaderSettings) -> str:
    fragments: list[str] = []
    position = 0
    for match in RUBY_PATTERN.finditer(text):
        fragments.append(html.escape(text[position : match.start()]))
        base = html.escape(match.group("base"))
        reading = html.escape(match.group("reading"))
        if settings.ruby_mode == RUBY_MODE:
            fragments.append(f'<ruby>{base}<rt aria-hidden="true">{reading}</rt></ruby>')
        elif settings.ruby_mode == HOVER_MODE:
            fragments.append(f'<span class="hover-ruby" title="{reading}">{base}</span>')
        else:
            fragments.append(base)
        position = match.end()
    fragments.append(html.escape(text[position:]))

    return "".join(fragments)


def render_reader_html(
    text: str,
    settings: ReaderSettings,
    document_key: str = "",
) -> str:
    font_family = html.escape(settings.font_family, quote=True)
    escaped_document_key = html.escape(document_key, quote=True)
    body = render_reader_body_html(text, settings)
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<style>
html, body {{ min-height: 100%; margin: 0; background: #ffffff; color: #202620; }}
body {{
  box-sizing: border-box;
  padding: 14px 16px 28px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: "{font_family}";
  font-size: {settings.font_size}px;
  line-height: 1.9;
  letter-spacing: 0;
}}
ruby {{ ruby-position: over; }}
rt {{ font-size: 0.55em; user-select: none; }}
.hover-ruby {{ text-decoration: underline dotted #8a968d; text-underline-offset: 3px; }}
</style>
</head>
<body data-legend-key="{escaped_document_key}">{body}</body>
</html>"""
