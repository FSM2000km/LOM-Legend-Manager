from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from legend_viewer.filename import build_target_path, sanitize_component


class FilenameTests(unittest.TestCase):
    def test_sanitize_windows_component(self) -> None:
        self.assertEqual("CON_", sanitize_component("CON"))
        self.assertEqual("江湖：引退？", sanitize_component("江湖:引退?"))
        self.assertEqual("不明", sanitize_component(" . "))

    def test_collision_adds_numeric_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            exported_at = datetime(2026, 8, 3, 1, 2, 3, tzinfo=timezone.utc)
            first = build_target_path(
                directory,
                "ED01",
                "回疆隠棲",
                "無結縁",
                exported_at,
                "0123abcd",
            )
            first.write_text("body", encoding="utf-8")
            second = build_target_path(
                directory,
                "ED01",
                "回疆隠棲",
                "無結縁",
                exported_at,
                "0123abcd",
            )
            self.assertTrue(second.name.endswith("_2.txt"))
            self.assertLessEqual(len(str(second)), 240)


if __name__ == "__main__":
    unittest.main()
