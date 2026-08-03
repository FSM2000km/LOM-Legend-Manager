from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from legend_viewer.paths import AppPaths
from legend_viewer.service import LegendService


HAS_PYSIDE = importlib.util.find_spec("PySide6") is not None
GAME_ROOT = Path(__file__).resolve().parents[2]


def make_paths(root: Path) -> AppPaths:
    persistent_root = root / "Mortal"
    manager_directory = persistent_root / "LegendManager"
    return AppPaths(
        game_root=GAME_ROOT,
        persistent_root=persistent_root,
        legend_directory=persistent_root / "Legend",
        manager_directory=manager_directory,
        inbox_directory=manager_directory / "inbox",
        processed_directory=manager_directory / "processed",
        failed_directory=manager_directory / "failed",
        database_path=manager_directory / "legend_manager.db",
        preset_path=GAME_ROOT / "LegendManager" / "data" / "jp_v2_4_presets.json",
        tag_catalog_path=GAME_ROOT / "LegendManager" / "data" / "tags_catalog.json",
    )


@unittest.skipUnless(HAS_PYSIDE, "PySide6が導入されていません。")
class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_fits_controls_and_hides_route_candidates(self) -> None:
        from PySide6.QtWidgets import QScrollArea

        from legend_viewer.ui import LegendMainWindow

        with tempfile.TemporaryDirectory() as temporary_directory:
            service = LegendService(make_paths(Path(temporary_directory)))
            path = service.paths.legend_directory / "LOM_Legend_20260803010207.txt"
            path.write_text("本文", encoding="utf-8")
            window = LegendMainWindow(service)
            window.show()
            self.app.processEvents()
            try:
                self.assertEqual(1, window.legend_tree.topLevelItemCount())
                self.assertLessEqual(
                    window.spoiler_button.geometry().right(),
                    window.spoiler_button.parentWidget().width(),
                )
                scroll = window.findChild(QScrollArea)
                assert scroll is not None
                self.assertLessEqual(
                    scroll.widget().width(), scroll.viewport().width() + 16
                )

                visible_labels = {
                    window.tag_combo.itemText(index)
                    for index in range(window.tag_combo.count())
                }
                self.assertTrue(any("金烏討伐成功" in label for label in visible_labels))
                self.assertFalse(any("西武林盟成立" in label for label in visible_labels))
                self.assertIn(
                    "唐嬌嬌",
                    {
                        window.heroine_combo.itemText(index)
                        for index in range(window.heroine_combo.count())
                    },
                )
            finally:
                window.close()
                service.close()


if __name__ == "__main__":
    unittest.main()
