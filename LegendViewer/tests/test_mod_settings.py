from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from legend_viewer.mod_settings import read_mod_settings, write_mod_settings


class ModSettingsTests(unittest.TestCase):
    def test_read_write_preserves_comments_unknowns_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "lom.jp.legendmanager.cfg"
            original = """## comment
[Export]
ShowAutoExportFileName = true
UnknownOption = keep-me

[General]
Enabled = true
DebounceMilliseconds = 750
"""
            path.write_text(original, encoding="utf-8", newline="")
            values = read_mod_settings(path)
            self.assertEqual("EndingDisplayed", values["AutoExportTiming"])
            values["AutoExportTiming"] = "EndingDisplayed"
            values["Enabled"] = False
            values["DebounceMilliseconds"] = 900

            backup = write_mod_settings(path, values)
            updated = path.read_text(encoding="utf-8")
            self.assertEqual(original, backup.read_text(encoding="utf-8"))
            self.assertIn("UnknownOption = keep-me", updated)
            self.assertIn("AutoExportTiming = EndingDisplayed", updated)
            self.assertIn("Enabled = false", updated)
            self.assertIn("DebounceMilliseconds = 900", updated)

    def test_legacy_disabled_auto_export_migrates_to_disabled_timing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "lom.jp.legendmanager.cfg"
            path.write_text("[Export]\nAutoExportOnSave = false\n", encoding="utf-8")
            self.assertEqual("Disabled", read_mod_settings(path)["AutoExportTiming"])


if __name__ == "__main__":
    unittest.main()
