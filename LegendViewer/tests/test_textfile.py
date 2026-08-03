from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legend_viewer.textfile import (
    MANAGED_TAG_END,
    MANAGED_TAG_START,
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
            self.assertNotIn("\n", second.text.replace("\r\n", ""))

    def test_normalization_uses_japanese_mod_aliases(self) -> None:
        self.assertEqual(
            "唐幇 江湖引退",
            normalize_for_matching("唐帮（とうほう）  江湖引退"),
        )


if __name__ == "__main__":
    unittest.main()
