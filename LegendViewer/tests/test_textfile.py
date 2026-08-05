from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legend_viewer.textfile import (
    MANAGED_INFO_END,
    MANAGED_INFO_START,
    MANAGED_TAG_END,
    MANAGED_TAG_START,
    embed_confirmed_information,
    embed_confirmed_tags,
    normalize_for_matching,
    read_legend,
)


class TextFileTests(unittest.TestCase):
    def test_embed_is_idempotent_and_preserves_body_bom_and_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "legend.txt"
            body = "第一行\r\n第二行\r\n"
            path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))

            before = read_legend(path)
            first = embed_confirmed_tags(path, ["ED01 回疆隠棲", "無結縁", "無結縁"])
            second = embed_confirmed_tags(path, ["ED01 回疆隠棲", "無結縁"])

            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(before.content_sha256, first.content_sha256)
            self.assertEqual(first.content_sha256, second.content_sha256)
            self.assertEqual(body, second.body_text)
            self.assertEqual(1, second.text.count(MANAGED_TAG_START))
            self.assertEqual(1, second.text.count(MANAGED_TAG_END))
            self.assertIn(MANAGED_TAG_END + "\r\n\r\n第一行", second.text)
            self.assertNotIn("\n", second.text.replace("\r\n", ""))

    def test_normalization_uses_japanese_mod_aliases(self) -> None:
        self.assertEqual(
            "唐幇 江湖引退",
            normalize_for_matching("唐帮（とうほう）  江湖引退"),
        )

    def test_information_block_replaces_legacy_block_and_preserves_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "legend.txt"
            path.write_text("本文\n", encoding="utf-8")
            before = embed_confirmed_tags(path, ["旧タグ"])
            updated = embed_confirmed_information(
                path,
                [
                    ("ED・結縁相手", ["ED: ED48 武林伝説", "結縁相手: 龍湘"]),
                    ("性情・処世・品性・道徳", ["- 性情: 豪快 (60)"]),
                ],
            )
            self.assertEqual(before.content_sha256, updated.content_sha256)
            self.assertNotIn(MANAGED_TAG_START, updated.text)
            self.assertEqual(1, updated.text.count(MANAGED_INFO_START))
            self.assertEqual(1, updated.text.count(MANAGED_INFO_END))
            self.assertIn("- 性情: 豪快 (60)", updated.text)


if __name__ == "__main__":
    unittest.main()
    embed_confirmed_information,
