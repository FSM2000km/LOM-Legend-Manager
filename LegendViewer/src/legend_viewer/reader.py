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


class LocalReaderPage(QWebEnginePage):
    def acceptNavigationRequest(
        self,
        url: QUrl,
        navigation_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        del navigation_type, is_main_frame
        return url.scheme() in ("about", "data")


def render_reader_html(text: str, settings: ReaderSettings) -> str:
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

    font_family = html.escape(settings.font_family, quote=True)
    body = "".join(fragments)
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
<body>{body}</body>
</html>"""
