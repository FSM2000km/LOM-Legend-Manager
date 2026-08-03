from __future__ import annotations

import unittest
from pathlib import Path

from legend_viewer.catalog import Catalog


GAME_ROOT = Path(__file__).resolve().parents[2]


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = Catalog(
            GAME_ROOT / "LegendManager" / "data" / "jp_v2_4_presets.json",
            GAME_ROOT / "LegendManager" / "data" / "tags_catalog.json",
        )

    def test_japanese_mod_catalog_counts(self) -> None:
        self.assertEqual(54, len(self.catalog.endings))
        self.assertEqual(123, len(self.catalog.tags))
        self.assertEqual("武林（ぶりん）伝説", self.catalog.endings[20047].name)

    def test_fixed_heroine_presets_are_complete(self) -> None:
        fixed = {
            ending.title_id: ending.heroine
            for ending in self.catalog.endings.values()
            if ending.heroine
        }
        self.assertEqual(
            {
                20008: "郁竹",
                20009: "郁竹",
                20012: "小師妹",
                20013: "小師妹",
                20014: "葉雲裳",
                20023: "龍湘",
                20025: "虞小梅",
                20026: "虞小梅",
                20027: "郁竹",
                20028: "郁竹",
                20029: "魏菊",
                20030: "夏侯蘭",
                20033: "夏侯蘭",
                20036: "小師妹",
                20037: "葉雲裳",
                20038: "上官螢",
                20039: "虞小梅",
                20040: "郁竹",
                20041: "魏菊",
                20042: "夏侯蘭",
                20043: "龍湘",
                20044: "無結縁",
                20045: "無結縁",
                20049: "唐嬌嬌",
                20052: "葉雲裳",
                20053: "葉雲裳",
            },
            fixed,
        )
        self.assertIn("heroine.tang_jiaojiao", self.catalog.tags)

    def test_default_picker_does_not_reveal_route_candidates(self) -> None:
        visible_labels = {tag.label for tag in self.catalog.ordered_tags()}
        self.assertIn("小師妹生存", visible_labels)
        self.assertIn("唐衫唐門加入", visible_labels)
        self.assertIn("金烏討伐成功", visible_labels)
        self.assertNotIn("西武林盟成立", visible_labels)
        self.assertNotIn("崆峒留学", visible_labels)
        self.assertNotIn("金烏未討伐", visible_labels)

    def test_confirmed_union_events_use_exact_story_keys(self) -> None:
        expected = {
            "小師妹結縁": "Ch_5_4_8_6_003",
            "葉雲裳結縁": "S0208_05_05_004",
            "上官螢結縁": "Ch_8_6_3_2_006",
            "虞小梅結縁": "Ch_8_6_3_2_007",
            "郁竹結縁": "Ch_4_6_16_010",
            "魏菊結縁": "Ch_6_4_4_2_002",
            "夏侯蘭結縁": "S2504_04_001",
            "龍湘結縁": "S0021_01_001",
        }

        for label, story_key in expected.items():
            with self.subTest(label=label):
                matches = self.catalog.rule_tags_for_story_keys([story_key])
                self.assertIn(label, {tag.label for tag in matches})


if __name__ == "__main__":
    unittest.main()
