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
    render_reader_body_html,
    render_reader_html,
)


class ReaderTests(unittest.TestCase):
    def test_ruby_modes_only_transform_cjk_with_kana_reading(self) -> None:
        text = "唐門（とうもん）へ行く（通常注記）"

        ruby = render_reader_html(text, ReaderSettings(ruby_mode=RUBY_MODE))
        ignored = render_reader_html(text, ReaderSettings(ruby_mode=IGNORE_MODE))
        hover = render_reader_html(text, ReaderSettings(ruby_mode=HOVER_MODE))

        self.assertIn("<ruby>唐門<rt", ruby)
        self.assertIn('data-legend-key=""', ruby)
        self.assertIn("行く（通常注記）", ruby)
        self.assertIn("唐門へ行く（通常注記）", ignored)
        self.assertIn('title="とうもん"', hover)

    def test_rendered_document_can_carry_a_legend_identity(self) -> None:
        html = render_reader_html("本文", ReaderSettings(), document_key="22")
        self.assertIn('data-legend-key="22"', html)

    def test_body_renderer_keeps_reader_markup_without_document_shell(self) -> None:
        body = render_reader_body_html("唐門（とうもん）", ReaderSettings())
        self.assertIn("<ruby>唐門<rt", body)
        self.assertNotIn("<!doctype html>", body)

    def test_settings_are_persisted_and_clamped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "viewer.ini"
            store = ReaderSettingsStore(path)
            store.save(ReaderSettings("Meiryo", 48, HOVER_MODE))
            self.assertEqual(ReaderSettings("Meiryo", 48, HOVER_MODE), store.load())

    def test_reading_position_requires_matching_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ReaderSettingsStore(Path(temporary) / "viewer.ini")
            store.save_last_legend_id(42)
            store.save_position(42, "hash-a", 0.625)
            self.assertEqual(42, store.load_last_legend_id())
            self.assertAlmostEqual(0.625, store.load_position(42, "hash-a"))
            self.assertEqual(0.0, store.load_position(42, "hash-b"))

    def test_legend_column_widths_are_persisted_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ReaderSettingsStore(Path(temporary) / "viewer.ini")
            widths = [112, 58, 52, 52, 52, 52, 72, 38, 100]
            store.save_legend_column_widths(widths)
            self.assertEqual(widths, store.load_legend_column_widths(9))
            self.assertIsNone(store.load_legend_column_widths(8))
