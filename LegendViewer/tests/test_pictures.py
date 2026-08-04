from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from legend_viewer.pictures import EndingPictureIndex


class EndingPictureIndexTests(unittest.TestCase):
    def test_resolves_collected_title_and_rejects_nested_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pictures = Path(temporary)
            image = pictures / "abc.png"
            image.write_bytes(b"png")
            index = pictures / "index.json"
            index.write_text(
                json.dumps({"endings": {"44": {"file": "abc.png"}}}),
                encoding="utf-8",
            )
            reader = EndingPictureIndex(pictures)
            self.assertEqual(image.resolve(), reader.picture_for_title(44))

            index.write_text(
                json.dumps({"endings": {"44": {"file": "../abc.png"}}}),
                encoding="utf-8",
            )
            self.assertIsNone(reader.picture_for_title(44))
