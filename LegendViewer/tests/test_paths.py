from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from legend_viewer.paths import AppPaths


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


if __name__ == "__main__":
    unittest.main()
