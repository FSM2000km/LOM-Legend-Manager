from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from legend_viewer.paths import AppPaths
from legend_viewer.path_settings import write_shared_settings


class AppPathsTests(unittest.TestCase):
    def test_frozen_executable_uses_bundled_catalog_from_any_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "任意の配置先" / "LegendViewer.exe"
            resource_root = root / "extracted_bundle"
            profile = root / "profile"

            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "_MEIPASS", str(resource_root), create=True),
                patch.object(sys, "executable", str(executable)),
                patch.dict(os.environ, {"USERPROFILE": str(profile)}),
            ):
                paths = AppPaths.discover()

            self.assertEqual(
                resource_root / "legend_data" / "jp_v2_4_presets.json",
                paths.preset_path,
            )
            self.assertEqual(
                resource_root / "legend_data" / "tags_catalog.json",
                paths.tag_catalog_path,
            )
            self.assertEqual(
                profile / "AppData" / "LocalLow" / "Obb Studio" / "Mortal",
                paths.persistent_root,
            )

    def test_configured_legend_directory_is_used_when_writable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "profile"
            persistent = profile / "AppData" / "LocalLow" / "Obb Studio" / "Mortal"
            configured = root / "custom legend"
            write_shared_settings(
                persistent / "LegendManager" / "settings.json",
                root / "game",
                configured,
            )
            with patch.dict(os.environ, {"USERPROFILE": str(profile)}):
                paths = AppPaths.discover()

            self.assertEqual(configured.resolve(), paths.legend_directory)
            self.assertTrue((configured / "Pictures").parent.is_dir())

    def test_unavailable_configured_directory_falls_back_without_rewriting_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "profile"
            persistent = profile / "AppData" / "LocalLow" / "Obb Studio" / "Mortal"
            settings_path = persistent / "LegendManager" / "settings.json"
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")
            configured = blocked_parent / "Legend"
            write_shared_settings(settings_path, root / "game", configured)
            original = settings_path.read_text(encoding="utf-8")

            with patch.dict(os.environ, {"USERPROFILE": str(profile)}):
                paths = AppPaths.discover()

            self.assertEqual(persistent / "Legend", paths.legend_directory)
            self.assertEqual(original, settings_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
