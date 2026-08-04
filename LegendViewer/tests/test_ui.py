from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
import json
from pathlib import Path

from legend_viewer.paths import AppPaths
from legend_viewer.service import LegendService
from legend_viewer.textfile import read_legend


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
        from legend_viewer.ui import LegendMainWindow

        with tempfile.TemporaryDirectory() as temporary_directory:
            service = LegendService(make_paths(Path(temporary_directory)))
            path = service.paths.legend_directory / "LOM_Legend_20260803010207.txt"
            path.write_text("武林（ぶりん）の本文", encoding="utf-8")
            document = read_legend(path)
            event = {
                "schema_version": 1,
                "event_id": "ui-parameters",
                "event_type": "legend_exported",
                "full_path": str(path),
                "content_sha256": document.content_sha256,
                "title_id": 20044,
                "story_keys": ["LegendInfo/Ch_5_4_8_10_001"],
                "confirmed_tags": [
                    {
                        "id": "event.4caf27318e01",
                        "label": "金烏上人死亡",
                        "category": "event",
                        "basis": "story_rule",
                        "confidence": "exact",
                    }
                ],
                "parameters": {
                    "abilities": [{"key": "0", "label": "体力", "value": 77}],
                    "personality": [
                        {
                            "key": "8",
                            "label": "性情",
                            "value": 60,
                            "display_value": "豪快",
                        }
                    ],
                    "relationships": [{"key": "12", "label": "龍湘", "value": 88}],
                    "skills": [{"key": "skill", "label": "技能", "level": 3}],
                },
            }
            (service.paths.inbox_directory / "ui-event.json").write_text(
                json.dumps(event, ensure_ascii=False), encoding="utf-8"
            )
            window = LegendMainWindow(service)
            window.show()
            self.app.processEvents()
            try:
                self.assertEqual(1, window.legend_tree.topLevelItemCount())
                self.assertLessEqual(
                    window.spoiler_button.geometry().right(),
                    window.spoiler_button.parentWidget().width(),
                )
                scroll = window.detail_panel
                self.assertLessEqual(
                    scroll.widget().width(), scroll.viewport().width() + 16
                )

                visible_labels = {
                    tag.label
                    for tag in service.catalog.ordered_tags(include_spoilers=False)
                    if tag.category not in ("ending", "heroine")
                }
                self.assertTrue(any("金烏上人死亡" in label for label in visible_labels))
                self.assertFalse(any("西武林盟成立" in label for label in visible_labels))
                self.assertEqual("タグ", window.legend_tree.headerItem().text(4))
                self.assertTrue(window.parameters_group.isVisible())
                self.assertEqual(4, window.parameters_tree.topLevelItemCount())
                self.assertEqual(
                    "豪快 (60)",
                    window.parameters_tree.topLevelItem(1).child(0).text(1),
                )
                self.assertFalse(window.parameters_tree.topLevelItem(0).isExpanded())
                self.assertFalse(hasattr(window, "category_combo"))
                self.assertTrue(window.top_tags_frame.isVisible())
                self.assertEqual(1, window.top_tag_layout.count())
                self.assertEqual(
                    "金烏上人死亡", window.top_tag_layout.itemAt(0).widget().text()
                )
                window.open_body_search()
                self.assertTrue(window.body_search_frame.isVisible())
                window.body_search_edit.setText("ぶりん")
                self.assertEqual("ぶりん", window.body_search_edit.text())
                window.close_body_search()
                self.assertFalse(window.body_search_frame.isVisible())
                window.library_panel_action.setChecked(False)
                window.detail_panel_action.setChecked(False)
                self.app.processEvents()
                self.assertFalse(window.library_panel.isVisible())
                self.assertFalse(window.detail_panel.isVisible())
                window.library_panel_action.setChecked(True)
                window.detail_panel_action.setChecked(True)
                self.app.processEvents()
                self.assertTrue(window.library_panel.isVisible())
                self.assertTrue(window.detail_panel.isVisible())
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
