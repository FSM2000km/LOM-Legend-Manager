from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legend_viewer.reader import (
    HOVER_MODE,
    IGNORE_MODE,
    RUBY_MODE,
    ReaderSettings,
    ReaderSettingsStore,
    render_reader_html,
)


class ReaderTests(unittest.TestCase):
    def test_ruby_modes_only_transform_cjk_with_kana_reading(self) -> None:
        text = "唐門（とうもん）へ行く（通常注記）"

        ruby = render_reader_html(text, ReaderSettings(ruby_mode=RUBY_MODE))
        ignored = render_reader_html(text, ReaderSettings(ruby_mode=IGNORE_MODE))
        hover = render_reader_html(text, ReaderSettings(ruby_mode=HOVER_MODE))

        self.assertIn("<ruby>唐門<rt", ruby)
        self.assertIn("行く（通常注記）", ruby)
        self.assertIn("唐門へ行く（通常注記）", ignored)
        self.assertIn('title="とうもん"', hover)

    def test_settings_are_persisted_and_clamped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "viewer.ini"
            store = ReaderSettingsStore(path)
            store.save(ReaderSettings("Meiryo", 48, HOVER_MODE))
            self.assertEqual(ReaderSettings("Meiryo", 48, HOVER_MODE), store.load())
