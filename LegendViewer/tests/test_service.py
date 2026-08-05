from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from legend_viewer.paths import AppPaths
from legend_viewer.service import LegendService
from legend_viewer.textfile import read_legend


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


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = make_paths(Path(self.temporary.name))
        self.service = LegendService(self.paths)

    def tearDown(self) -> None:
        self.service.close()
        self.temporary.cleanup()

    def test_list_filters_by_ending_heroine_and_multiple_tags(self) -> None:
        first_path = self.paths.legend_directory / "LOM_Legend_20260805010101.txt"
        second_path = self.paths.legend_directory / "LOM_Legend_20260805010102.txt"
        first_path.write_text("一つ目の本文", encoding="utf-8")
        second_path.write_text("二つ目の本文", encoding="utf-8")
        self.service.sync()
        rows = self.service.database.list_legends()
        ids = {row["current_file_name"]: int(row["id"]) for row in rows}
        first_id = ids[first_path.name]
        second_id = ids[second_path.name]
        self.service.set_metadata(first_id, 20044, 0)
        self.service.set_metadata(second_id, 20047, 2)
        shared_tag = self.service.add_freeform_tag(first_id, "共有タグ")
        self.service.add_freeform_tag(second_id, "共有タグ")
        exclusive_tag = self.service.add_freeform_tag(first_id, "限定タグ")

        self.assertEqual(1, len(self.service.database.list_legends(title_ids={20044})))
        self.assertEqual(1, len(self.service.database.list_legends(heroine_ids={2})))
        self.assertEqual(
            1,
            len(
                self.service.database.list_legends(
                    tag_ids={shared_tag, exclusive_tag}, require_all_tags=True
                )
            ),
        )
        self.assertEqual(
            2,
            len(
                self.service.database.list_legends(
                    tag_ids={shared_tag, exclusive_tag}, require_all_tags=False
                )
            ),
        )

    def test_mod_event_survives_later_file_scans(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260803010203.txt"
        path.write_text("観測した伝説本文\r\n", encoding="utf-8", newline="")
        self.service.sync()

        document = read_legend(path)
        event = {
            "schema_version": 1,
            "event_id": "event-exact-1",
            "event_type": "legend_exported",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20044,
            "file_prefix": "ED45",
            "title_name": "最後の唐門（とうもん）弟子",
            "partner_id": 0,
            "exported_at": "2026-08-03T01:02:03+09:00",
            "original_file_name": path.name,
            "slot": 4,
            "end_key": "20044",
            "story_keys": ["Ch_6_8_3_020"],
            "story_key_sha256": "story-hash",
            "confirmed_tags": [],
        }
        event_path = self.paths.inbox_directory / "event.json"
        event_path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")

        result = self.service.sync()
        self.assertEqual(1, result.inbox_imported)
        legend = dict(self.service.database.list_legends()[0])
        detail = self.service.database.get_legend(int(legend["id"]))
        assert detail is not None
        self.assertEqual("event-exact-1", detail["source_event_id"])
        self.assertEqual("最後の唐門（とうもん）弟子", detail["title_name"])
        self.assertEqual("無結縁", detail["heroine"])
        self.assertEqual("game_end_key", detail["title_source"])
        self.assertEqual(["Ch_6_8_3_020"], json.loads(detail["story_keys_json"]))
        self.assertIn("唐衫唐門加入", {tag["label"] for tag in detail["tags"]})

        self.service.scan_legend_directory()
        detail = self.service.database.get_legend(int(legend["id"]))
        assert detail is not None
        self.assertEqual("event-exact-1", detail["source_event_id"])
        self.assertEqual("最後の唐門（とうもん）弟子", detail["title_name"])
        self.assertEqual("無結縁", detail["heroine"])
        self.assertIn("唐衫唐門加入", {tag["label"] for tag in detail["tags"]})

    def test_parameter_snapshot_is_imported_and_survives_file_scan(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260805010203.txt"
        path.write_text("パラメータ付き伝説本文\r\n", encoding="utf-8", newline="")
        document = read_legend(path)
        parameters = {
            "abilities": [{"key": "0", "label": "体力", "value": 77}],
            "personality": [{"key": "8", "label": "性情", "value": 42}],
            "resources": [{"key": "3", "label": "所持金", "value": 1234}],
            "faction": [
                {"key": "14", "label": "名声", "value": 31},
                {"key": "16", "label": "団結", "value": 65},
            ],
            "relationships": [{"key": "12", "label": "龍湘", "value": 88}],
            "skills": [{"key": "skill.test", "label": "テスト技能", "level": 3}],
        }
        event = {
            "schema_version": 1,
            "event_id": "event-parameters",
            "event_type": "legend_exported",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20044,
            "story_keys": [],
            "confirmed_tags": [],
            "parameters": parameters,
        }
        (self.paths.inbox_directory / "parameters.json").write_text(
            json.dumps(event, ensure_ascii=False), encoding="utf-8"
        )

        self.service.sync()
        legend_id = int(self.service.database.list_legends()[0]["id"])
        detail = self.service.database.get_legend(legend_id)
        assert detail is not None
        self.assertEqual(parameters, detail["parameters"])

        self.service.scan_legend_directory()
        detail = self.service.database.get_legend(legend_id)
        assert detail is not None
        self.assertEqual(parameters, detail["parameters"])

    def test_ending_heroine_preset_sets_union(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260803010208.txt"
        path.write_text("生ける屍の本文", encoding="utf-8")
        document = read_legend(path)
        event = {
            "schema_version": 1,
            "event_id": "event-ending-heroine",
            "event_type": "legend_exported",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20033,
            "partner_id": None,
            "story_keys": [],
            "confirmed_tags": [],
        }
        (self.paths.inbox_directory / "event.json").write_text(
            json.dumps(event, ensure_ascii=False), encoding="utf-8"
        )

        self.service.sync()
        detail = self.service.database.get_legend(
            int(self.service.database.list_legends()[0]["id"])
        )
        assert detail is not None
        self.assertEqual(5, detail["heroine_id"])
        self.assertEqual("夏侯蘭", detail["heroine"])
        self.assertEqual("ending_preset", detail["heroine_source"])
        self.assertIn("heroine.5", {tag["id"] for tag in detail["tags"]})

    def test_no_union_ending_overrides_prior_union_story_key(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260803010213.txt"
        path.write_text("敗者の末路本文", encoding="utf-8")
        document = read_legend(path)
        event = {
            "schema_version": 1,
            "event_id": "event-fixed-no-union",
            "event_type": "legend_exported",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20023,
            "partner_id": 2,
            "story_keys": ["S0021_01_001"],
            "confirmed_tags": [],
        }
        (self.paths.inbox_directory / "event.json").write_text(
            json.dumps(event, ensure_ascii=False), encoding="utf-8"
        )

        self.service.sync()
        detail = self.service.database.get_legend(
            int(self.service.database.list_legends()[0]["id"])
        )
        assert detail is not None
        self.assertEqual(0, detail["heroine_id"])
        self.assertEqual("無結縁", detail["heroine"])
        self.assertEqual("ending_preset", detail["heroine_source"])
        self.assertIn("heroine.none", {tag["id"] for tag in detail["tags"]})

    def test_ed25_uses_observed_union_story_key(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260803010214.txt"
        path.write_text("武林盟主本文", encoding="utf-8")
        document = read_legend(path)
        event = {
            "schema_version": 1,
            "event_id": "event-ed25-dynamic-union",
            "event_type": "legend_exported",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20024,
            "partner_id": None,
            "story_keys": ["S0021_01_001"],
            "confirmed_tags": [],
        }
        (self.paths.inbox_directory / "event.json").write_text(
            json.dumps(event, ensure_ascii=False), encoding="utf-8"
        )

        self.service.sync()
        detail = self.service.database.get_legend(
            int(self.service.database.list_legends()[0]["id"])
        )
        assert detail is not None
        self.assertEqual(2, detail["heroine_id"])
        self.assertEqual("龍湘", detail["heroine"])
        self.assertEqual("story_rule", detail["heroine_source"])

    def test_ed25_without_observed_union_stays_unknown(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260803010215.txt"
        path.write_text("武林盟主未結縁本文", encoding="utf-8")
        document = read_legend(path)
        event = {
            "schema_version": 1,
            "event_id": "event-ed25-dynamic-unknown",
            "event_type": "legend_exported",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20024,
            "partner_id": None,
            "story_keys": [],
            "confirmed_tags": [],
        }
        (self.paths.inbox_directory / "event.json").write_text(
            json.dumps(event, ensure_ascii=False), encoding="utf-8"
        )

        self.service.sync()
        detail = self.service.database.get_legend(
            int(self.service.database.list_legends()[0]["id"])
        )
        assert detail is not None
        self.assertIsNone(detail["heroine_id"])
        self.assertIsNone(detail["heroine"])
        self.assertEqual("unknown", detail["heroine_source"])

    def test_game_title_partner_does_not_imply_union(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260803010209.txt"
        path.write_text("矛盾検証用本文", encoding="utf-8")
        document = read_legend(path)
        event = {
            "schema_version": 1,
            "event_id": "event-game-partner-wins",
            "event_type": "legend_exported",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20024,
            "partner_id": 2,
            "story_keys": [],
            "confirmed_tags": [],
        }
        (self.paths.inbox_directory / "event.json").write_text(
            json.dumps(event, ensure_ascii=False), encoding="utf-8"
        )

        self.service.sync()
        detail = self.service.database.get_legend(
            int(self.service.database.list_legends()[0]["id"])
        )
        assert detail is not None
        self.assertIsNone(detail["heroine_id"])
        self.assertIsNone(detail["heroine"])
        self.assertEqual("unknown", detail["heroine_source"])
        self.assertNotIn("heroine.2", {tag["id"] for tag in detail["tags"]})

    def test_latest_long_xiang_route_without_union_stays_unknown(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260803155151.txt"
        path.write_text("最新Legend相当本文", encoding="utf-8")
        document = read_legend(path)
        event = {
            "schema_version": 1,
            "event_id": "event-latest-no-union",
            "event_type": "legend_exported",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20047,
            "partner_id": 2,
            "story_keys": [
                "S0022_01_02_009",
                "Ch_6_7_5_016",
                "Ch_6_8_2_Break_01_005",
            ],
            "confirmed_tags": [
                {
                    "id": "heroine.2",
                    "label": "龍湘",
                    "category": "heroine",
                    "basis": "game_title_partner",
                    "confidence": "exact",
                }
            ],
        }
        (self.paths.inbox_directory / "event.json").write_text(
            json.dumps(event, ensure_ascii=False), encoding="utf-8"
        )

        self.service.sync()
        detail = self.service.database.get_legend(
            int(self.service.database.list_legends()[0]["id"])
        )
        assert detail is not None
        self.assertIsNone(detail["heroine_id"])
        self.assertIsNone(detail["heroine"])
        self.assertEqual("unknown", detail["heroine_source"])
        self.assertNotIn("heroine.2", {tag["id"] for tag in detail["tags"]})

    def test_union_story_key_overrides_different_title_partner(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260803010212.txt"
        path.write_text("龍湘結縁本文", encoding="utf-8")
        document = read_legend(path)
        event = {
            "schema_version": 1,
            "event_id": "event-union-story-wins",
            "event_type": "legend_exported",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20047,
            "partner_id": 3,
            "story_keys": ["S0021_01_001"],
            "confirmed_tags": [],
        }
        (self.paths.inbox_directory / "event.json").write_text(
            json.dumps(event, ensure_ascii=False), encoding="utf-8"
        )

        self.service.sync()
        detail = self.service.database.get_legend(
            int(self.service.database.list_legends()[0]["id"])
        )
        assert detail is not None
        self.assertEqual(2, detail["heroine_id"])
        self.assertEqual("龍湘", detail["heroine"])
        self.assertEqual("story_rule", detail["heroine_source"])
        self.assertIn("heroine.2", {tag["id"] for tag in detail["tags"]})

    def test_tang_jiaojiao_ending_sets_union(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260803010210.txt"
        path.write_text("峨嵋弟子の本文", encoding="utf-8")
        document = read_legend(path)
        event = {
            "schema_version": 1,
            "event_id": "event-tang-jiaojiao",
            "event_type": "legend_exported",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20049,
            "partner_id": None,
            "story_keys": [],
            "confirmed_tags": [],
        }
        (self.paths.inbox_directory / "event.json").write_text(
            json.dumps(event, ensure_ascii=False), encoding="utf-8"
        )

        self.service.sync()
        detail = self.service.database.get_legend(
            int(self.service.database.list_legends()[0]["id"])
        )
        assert detail is not None
        self.assertEqual(-1, detail["heroine_id"])
        self.assertEqual("唐嬌嬌", detail["heroine"])
        self.assertEqual("ending_preset", detail["heroine_source"])
        self.assertIn("heroine.tang_jiaojiao", {tag["id"] for tag in detail["tags"]})

    def test_ending_preset_does_not_override_filename_relationship(self) -> None:
        path = (
            self.paths.legend_directory
            / "ED34_生ける屍_龍湘_20260803010211_0123abcd.txt"
        )
        path.write_text("既存ファイルの本文", encoding="utf-8")

        self.service.sync()
        detail = self.service.database.get_legend(
            int(self.service.database.list_legends()[0]["id"])
        )
        assert detail is not None
        self.assertEqual(20033, detail["title_id"])
        self.assertEqual(2, detail["heroine_id"])
        self.assertEqual("龍湘", detail["heroine"])
        self.assertEqual("filename", detail["heroine_source"])
        self.assertIn("heroine.2", {tag["id"] for tag in detail["tags"]})

    def test_manual_metadata_tags_are_protected_from_event_reimport(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260803010204.txt"
        path.write_text("本文", encoding="utf-8")
        self.service.sync()
        legend_id = int(self.service.database.list_legends()[0]["id"])
        self.service.set_metadata(legend_id, 20001, 2)

        document = read_legend(path)
        event = {
            "schema_version": 1,
            "event_id": "event-after-manual",
            "event_type": "legend_exported",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20033,
            "partner_id": None,
            "story_keys": ["S2504_04_001"],
            "confirmed_tags": [],
        }
        (self.paths.inbox_directory / "event.json").write_text(
            json.dumps(event, ensure_ascii=False), encoding="utf-8"
        )
        self.service.sync()

        detail = self.service.database.get_legend(legend_id)
        assert detail is not None
        self.assertEqual(20001, detail["title_id"])
        self.assertEqual(2, detail["heroine_id"])
        ending_tags = [tag for tag in detail["tags"] if tag["category"] == "ending"]
        heroine_tags = [tag for tag in detail["tags"] if tag["category"] == "heroine"]
        self.assertEqual(["ending.20001"], [tag["id"] for tag in ending_tags])
        self.assertEqual(["heroine.2"], [tag["id"] for tag in heroine_tags])

    def test_existing_slot_match_keeps_filename_heroine_and_is_idempotent(self) -> None:
        path = self.paths.legend_directory / "ED名不明_龍湘_20260803010207_0123abcd.txt"
        path.write_text("既存伝説本文\r\n", encoding="utf-8", newline="")
        self.service.sync()

        document = read_legend(path)
        event = {
            "schema_version": 1,
            "event_id": "existing-slot-exact-1",
            "event_type": "legend_exported",
            "source": "existing_slot_exact",
            "full_path": str(path),
            "content_sha256": document.content_sha256,
            "title_id": 20000,
            "partner_id": None,
            "slot": 1,
            "end_key": "20000",
            "story_keys": [],
            "confirmed_tags": [],
        }
        event_path = self.paths.inbox_directory / "existing.json"
        event_path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
        self.service.sync()

        detail = self.service.database.get_legend(
            int(self.service.database.list_legends()[0]["id"])
        )
        assert detail is not None
        self.assertEqual("回疆隠棲", detail["title_name"])
        self.assertEqual("game_end_key", detail["title_source"])
        self.assertEqual("filename", detail["confidence"])
        self.assertEqual("龍湘", detail["heroine"])
        self.assertEqual("filename", detail["heroine_source"])
        self.assertIn("heroine.2", {tag["id"] for tag in detail["tags"]})

        event_path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
        self.service.sync()
        self.assertEqual(1, len(self.service.database.list_legends()))

    def test_embed_preserves_body_and_detects_external_changes(self) -> None:
        path = self.paths.legend_directory / "LOM_Legend_20260803010205.txt"
        path.write_text("本文\r\n", encoding="utf-8", newline="")
        self.service.sync()
        legend_id = int(self.service.database.list_legends()[0]["id"])
        self.service.set_metadata(legend_id, 20000, 0)
        before = read_legend(path)

        self.service.embed_tags(legend_id)
        after = read_legend(path)
        self.assertEqual(before.content_sha256, after.content_sha256)
        self.service.embed_tags(legend_id)
        self.assertEqual(1, read_legend(path).text.count("【確定済みタグ】"))

        path.write_text(read_legend(path).text + "外部編集", encoding="utf-8", newline="")
        with self.assertRaisesRegex(RuntimeError, "外部編集"):
            self.service.embed_tags(legend_id)

    def test_unknown_relationship_filename_keeps_timestamp(self) -> None:
        path = self.paths.legend_directory / "ED名不明_結縁相手不明_20260803010206_0123abcd.txt"
        path.write_text("本文", encoding="utf-8")
        self.service.sync()

        detail = self.service.database.get_legend(
            int(self.service.database.list_legends()[0]["id"])
        )
        assert detail is not None
        self.assertIsNone(detail["title_id"])
        self.assertIsNone(detail["heroine"])
        self.assertEqual("unknown", detail["heroine_source"])
        self.assertTrue(detail["exported_at"].startswith("2026-08-03T01:02:06"))


if __name__ == "__main__":
    unittest.main()
