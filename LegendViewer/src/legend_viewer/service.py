from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .catalog import Catalog, EndingDefinition, TagDefinition
from .database import LegendDatabase, utc_now
from .filename import build_target_path
from .paths import AppPaths
from .textfile import EXPORT_TIMESTAMP_PATTERN, embed_confirmed_tags, read_legend


HEROINE_BY_ID = {
    -1: "唐嬌嬌",
    0: "無結縁",
    1: "小師妹",
    2: "龍湘",
    3: "葉雲裳",
    4: "上官螢",
    5: "夏侯蘭",
    6: "虞小梅",
    7: "魏菊",
    8: "郁竹",
    20: "無結縁",
}
HEROINE_SELECTION_IDS = (0, 1, 2, 3, 4, 5, 6, 7, 8, -1)
HEROINE_ID_BY_NAME = {
    name: heroine_id
    for heroine_id, name in HEROINE_BY_ID.items()
    if heroine_id != 20
}


def heroine_tag_id(heroine_id: int | None) -> str | None:
    if heroine_id is None:
        return None
    if heroine_id in (0, 20):
        return "heroine.none"
    if heroine_id == -1:
        return "heroine.tang_jiaojiao"
    return f"heroine.{heroine_id}"


def resolve_union(
    catalog: Catalog,
    ending: EndingDefinition | None,
    story_keys: Iterable[str],
) -> tuple[int | None, str | None, str]:
    if ending and ending.heroine in HEROINE_ID_BY_NAME:
        heroine_id = HEROINE_ID_BY_NAME[ending.heroine]
        return heroine_id, ending.heroine, "ending_preset"

    heroine_ids = {
        HEROINE_ID_BY_NAME[tag.label.removesuffix("結縁")]
        for tag in catalog.rule_tags_for_story_keys(story_keys)
        if tag.label.endswith("結縁")
        and tag.label.removesuffix("結縁") in HEROINE_ID_BY_NAME
    }
    if len(heroine_ids) == 1:
        heroine_id = heroine_ids.pop()
        return heroine_id, HEROINE_BY_ID[heroine_id], "story_rule"
    return None, None, "unknown"


UNKNOWN_RELATIONSHIP_NAMES = ("結縁相手不明", "ヒロイン名不明")
TARGET_FILE_PATTERN = re.compile(
    r"^(?P<prefix>ED\d+)_(?P<title>.+)_(?P<heroine>"
    + "|".join(re.escape(name) for name in (*HEROINE_ID_BY_NAME, *UNKNOWN_RELATIONSHIP_NAMES))
    + r")_(?P<timestamp>\d{14})_(?P<hash>[0-9a-fA-F]{8})(?:_\d+)?\.txt$"
)
UNKNOWN_TARGET_FILE_PATTERN = re.compile(
    r"^ED名不明_(?P<heroine>"
    + "|".join(re.escape(name) for name in (*HEROINE_ID_BY_NAME, *UNKNOWN_RELATIONSHIP_NAMES))
    + r")_(?P<timestamp>\d{14})_(?P<hash>[0-9a-fA-F]{8})(?:_\d+)?\.txt$"
)


@dataclass(frozen=True)
class SyncResult:
    inbox_imported: int = 0
    inbox_failed: int = 0
    scanned: int = 0


class LegendService:
    def __init__(self, paths: AppPaths | None = None) -> None:
        self.paths = paths or AppPaths.discover()
        self.paths.ensure_directories()
        self.catalog = Catalog(self.paths.preset_path, self.paths.tag_catalog_path)
        self.database = LegendDatabase(self.paths.database_path)
        self.database.sync_catalog(self.catalog)

    def close(self) -> None:
        self.database.close()

    def sync(self, scan_files: bool = True) -> SyncResult:
        imported, failed = self.import_inbox()
        scanned = self.scan_legend_directory() if scan_files else 0
        self._reconcile_relationships()
        self.database.recompute_duplicates()
        self.database.mark_missing_files()
        return SyncResult(imported, failed, scanned)

    def import_inbox(self) -> tuple[int, int]:
        imported = 0
        failed = 0
        for event_path in sorted(self.paths.inbox_directory.glob("*.json")):
            try:
                self._import_event_file(event_path)
                self._archive_event(event_path, self.paths.processed_directory)
                imported += 1
            except Exception as exception:
                failed += 1
                error_path = event_path.with_suffix(event_path.suffix + ".error.txt")
                error_path.write_text(f"{type(exception).__name__}: {exception}\n", encoding="utf-8")
                self._archive_event(event_path, self.paths.failed_directory)
                self._archive_event(error_path, self.paths.failed_directory)
        return imported, failed

    def _import_event_file(self, event_path: Path) -> int:
        with event_path.open("r", encoding="utf-8") as handle:
            event: dict[str, Any] = json.load(handle)
        if int(event.get("schema_version", 0)) != 1:
            raise ValueError("未対応のMODイベント形式です。")
        if event.get("event_type") != "legend_exported":
            raise ValueError("未対応のMODイベント種別です。")

        full_path = self._validate_legend_path(Path(event["full_path"]))
        if not full_path.exists():
            raise FileNotFoundError(full_path)
        document = read_legend(full_path)
        if document.content_sha256 != event["content_sha256"]:
            raise ValueError("MODイベントとTXTの本文ハッシュが一致しません。")

        title_id = event.get("title_id")
        ending = self.catalog.find_ending(
            int(title_id) if title_id is not None else None,
            event.get("file_prefix"),
            event.get("title_name"),
        )
        story_keys = list(event.get("story_keys") or [])
        heroine_id, heroine, heroine_source = resolve_union(
            self.catalog, ending, story_keys
        )

        record = {
            "source_event_id": event["event_id"],
            "content_sha256": document.content_sha256,
            "normalized_sha256": document.normalized_sha256,
            "file_sha256": document.file_sha256,
            "original_file_name": event.get("original_file_name") or full_path.name,
            "full_path": str(full_path),
            "exported_at": event.get("exported_at"),
            "file_size": document.file_size,
            "kind": "ending",
            "title_id": ending.title_id if ending else None,
            "file_prefix": ending.file_prefix if ending else None,
            "title_name": ending.name if ending else None,
            "title_source": "game_end_key" if ending else "unknown",
            "heroine_id": heroine_id,
            "heroine": heroine,
            "heroine_source": heroine_source,
            "end_key": event.get("end_key"),
            "slot": event.get("slot"),
            "confidence": "exact" if ending and heroine is not None else "partial",
            "story_keys": story_keys,
            "story_key_sha256": event.get("story_key_sha256"),
        }
        legend_id = self.database.upsert_legend(record, document.body_text)

        assignments: list[tuple[str, str, str]] = []
        for item in event.get("confirmed_tags") or []:
            tag_id = item.get("id")
            tag = self.catalog.tags.get(tag_id)
            if tag and not (
                tag.category == "heroine"
                and item.get("basis") in ("game_title_partner", "saved_slot_metadata")
            ):
                assignments.append((tag_id, "mod", item.get("confidence") or "exact"))
        if ending:
            assignments.append((ending.tag_id, "mod", "exact"))
        if heroine is not None:
            tag_id = heroine_tag_id(heroine_id)
            if tag_id:
                assignments.append((tag_id, "mod", "exact"))
        else:
            current = self.database.get_legend(legend_id)
            if current and current.get("heroine"):
                current_heroine_id = current.get("heroine_id")
                heroine_tag = heroine_tag_id(current_heroine_id)
                if heroine_tag in self.catalog.tags:
                    assignments.append(
                        (heroine_tag, current.get("heroine_source") or "scan", "filename")
                    )
        assignments.extend(
            (tag.id, "story_rule", "exact")
            for tag in self.catalog.rule_tags_for_story_keys(story_keys)
        )
        self.database.replace_automatic_tags(legend_id, assignments)
        return legend_id

    def scan_legend_directory(self) -> int:
        count = 0
        for path in sorted(self.paths.legend_directory.glob("*.txt")):
            if path.name.startswith(".") or path.name.endswith(".tmp"):
                continue
            self._scan_file(path)
            count += 1
        return count

    def _scan_file(self, path: Path) -> int:
        full_path = self._validate_legend_path(path)
        document = read_legend(full_path)
        ending, heroine_id, heroine, exported_at = self._metadata_from_file_name(full_path)
        heroine_source = "filename" if heroine else "unknown"
        source_event_id = "scan." + hashlib.sha256(str(full_path).casefold().encode("utf-8")).hexdigest()
        record = {
            "source_event_id": source_event_id,
            "content_sha256": document.content_sha256,
            "normalized_sha256": document.normalized_sha256,
            "file_sha256": document.file_sha256,
            "original_file_name": full_path.name,
            "full_path": str(full_path),
            "exported_at": exported_at.isoformat() if exported_at else None,
            "file_size": document.file_size,
            "kind": "ending",
            "title_id": ending.title_id if ending else None,
            "file_prefix": ending.file_prefix if ending else None,
            "title_name": ending.name if ending else None,
            "title_source": "filename" if ending else "unknown",
            "heroine_id": heroine_id,
            "heroine": heroine,
            "heroine_source": heroine_source,
            "end_key": str(ending.title_id) if ending else None,
            "slot": None,
            "confidence": "filename" if ending or heroine else "low",
            "story_keys": [],
            "story_key_sha256": None,
        }
        legend_id = self.database.upsert_legend(record, document.body_text)

        existing = self.database.get_legend(legend_id)
        assignments: list[tuple[str, str, str]] = []
        if ending and existing and existing["title_source"] == "filename":
            assignments.append((ending.tag_id, "scan", "filename"))
        if (
            heroine
            and existing
            and existing["heroine_source"] in ("filename", "ending_preset")
        ):
            tag_id = heroine_tag_id(heroine_id)
            if tag_id:
                confidence = "exact" if heroine_source == "ending_preset" else "filename"
                assignments.append((tag_id, "scan", confidence))
        if existing and str(existing.get("source_event_id", "")).startswith("scan."):
            self.database.replace_automatic_tags(legend_id, assignments)
        return legend_id

    def _metadata_from_file_name(
        self,
        path: Path,
    ) -> tuple[EndingDefinition | None, int | None, str | None, datetime | None]:
        ending = None
        heroine_id = None
        heroine = None
        exported_at = None
        match = TARGET_FILE_PATTERN.match(path.name)
        if match:
            ending = self.catalog.find_ending(
                None,
                match.group("prefix"),
                match.group("title"),
            )
            heroine = match.group("heroine")
            heroine_id = HEROINE_ID_BY_NAME.get(heroine)
            if heroine in UNKNOWN_RELATIONSHIP_NAMES:
                heroine = None
            exported_at = datetime.strptime(match.group("timestamp"), "%Y%m%d%H%M%S").astimezone()
            return ending, heroine_id, heroine, exported_at

        unknown_match = UNKNOWN_TARGET_FILE_PATTERN.match(path.name)
        if unknown_match:
            heroine = unknown_match.group("heroine")
            heroine_id = HEROINE_ID_BY_NAME.get(heroine)
            if heroine in UNKNOWN_RELATIONSHIP_NAMES:
                heroine = None
            exported_at = datetime.strptime(
                unknown_match.group("timestamp"), "%Y%m%d%H%M%S"
            ).astimezone()
            return None, heroine_id, heroine, exported_at

        timestamp_match = EXPORT_TIMESTAMP_PATTERN.search(path.name)
        if timestamp_match:
            exported_at = datetime.strptime(
                timestamp_match.group("timestamp"), "%Y%m%d%H%M%S"
            ).astimezone()

        for name, candidate_id in HEROINE_ID_BY_NAME.items():
            if path.stem.startswith(name + "_"):
                heroine = name
                heroine_id = candidate_id
                remainder = path.stem[len(name) + 1 :]
                ending = self.catalog.find_ending(None, None, remainder)
                break
        return ending, heroine_id, heroine, exported_at

    def _reconcile_relationships(self) -> None:
        for row in self.database.list_legends():
            legend_id = int(row["id"])
            detail = self.database.get_legend(legend_id)
            if detail is None:
                continue

            story_keys = list(json.loads(detail.get("story_keys_json") or "[]"))
            ending = self.catalog.find_ending(
                detail.get("title_id"),
                detail.get("file_prefix"),
                detail.get("title_name"),
            )
            heroine_id, heroine, heroine_source = resolve_union(
                self.catalog, ending, story_keys
            )

            if (
                not story_keys
                and detail.get("heroine_source") == "filename"
                and detail.get("heroine")
            ):
                heroine_id = detail.get("heroine_id")
                heroine = detail.get("heroine")
                heroine_source = "filename"

            if detail.get("heroine_source") != "manual":
                self.database.set_automatic_relationship(
                    legend_id,
                    heroine_id,
                    heroine,
                    heroine_source,
                )

            assignments: list[tuple[str, str, str]] = []
            if ending:
                assignments.append((ending.tag_id, "reconcile", "exact"))
            relationship_tag = heroine_tag_id(heroine_id)
            if relationship_tag:
                assignments.append(
                    (relationship_tag, heroine_source, "exact" if heroine_source != "filename" else "filename")
                )
            assignments.extend(
                (tag.id, "story_rule", "exact")
                for tag in self.catalog.rule_tags_for_story_keys(story_keys)
            )
            self.database.replace_automatic_tags(legend_id, assignments)

    def embed_tags(self, legend_id: int) -> None:
        legend = self._require_legend(legend_id)
        path = self._validate_legend_path(Path(legend["full_path"]))
        before = read_legend(path)
        if before.content_sha256 != legend["content_sha256"]:
            raise RuntimeError("外部編集で本文が変わっています。再読込してから実行してください。")
        labels = self.database.confirmed_tag_labels(legend_id)
        updated = embed_confirmed_tags(path, labels)
        self.database.update_file_state(
            legend_id,
            file_sha256=updated.file_sha256,
            file_size=updated.file_size,
            tags_embedded_at=utc_now(),
        )

    def rename_legend(self, legend_id: int) -> Path:
        legend = self._require_legend(legend_id)
        if not legend.get("file_prefix") or not legend.get("title_name"):
            raise ValueError("ED名を確定してからリネームしてください。")
        if not legend.get("heroine"):
            raise ValueError("結縁相手または無結縁を確定してからリネームしてください。")

        source = self._validate_legend_path(Path(legend["full_path"]))
        exported_at = self._parse_datetime(legend.get("exported_at")) or datetime.fromtimestamp(
            source.stat().st_mtime
        ).astimezone()
        target = build_target_path(
            self.paths.legend_directory,
            legend["file_prefix"],
            legend["title_name"],
            legend["heroine"],
            exported_at,
            legend["hash8"],
            source,
        )
        if target.resolve() != source.resolve():
            source.rename(target)
            self.database.update_file_state(legend_id, full_path=target)
        return target

    def set_metadata(self, legend_id: int, title_id: int | None, heroine_id: int | None) -> None:
        ending = self.catalog.endings.get(title_id) if title_id is not None else None
        heroine = HEROINE_BY_ID.get(heroine_id) if heroine_id is not None else None
        self.database.set_metadata(
            legend_id,
            ending,
            heroine_id,
            heroine,
            heroine_tag_id(heroine_id),
        )

    def add_tag(self, legend_id: int, tag_id: str) -> None:
        if tag_id not in self.catalog.tags:
            raise KeyError(tag_id)
        self.database.add_manual_tag(legend_id, tag_id)

    def add_freeform_tag(self, legend_id: int, label: str) -> str:
        return self.database.add_freeform_tag(legend_id, label)

    def remove_tag(self, legend_id: int, tag_id: str) -> None:
        self.database.remove_tag(legend_id, tag_id)

    def update_note(self, legend_id: int, note: str) -> None:
        self.database.update_note(legend_id, note)

    def create_backup(self) -> Path:
        backup_directory = self.paths.manager_directory / "backups"
        destination = backup_directory / f"legend_manager_{datetime.now():%Y%m%d_%H%M%S}.db"
        self.database.backup(destination)
        return destination

    def _validate_legend_path(self, path: Path) -> Path:
        resolved = path.resolve()
        legend_root = self.paths.legend_directory.resolve()
        if os.path.commonpath((resolved, legend_root)) != str(legend_root):
            raise ValueError("伝説フォルダ外のファイルは処理できません。")
        if resolved.suffix.casefold() != ".txt":
            raise ValueError("TXT以外のファイルは処理できません。")
        return resolved

    @staticmethod
    def _archive_event(source: Path, destination_directory: Path) -> None:
        if not source.exists():
            return
        destination_directory.mkdir(parents=True, exist_ok=True)
        destination = destination_directory / source.name
        if destination.exists():
            destination = destination.with_name(
                f"{destination.stem}_{datetime.now():%Y%m%d%H%M%S%f}{destination.suffix}"
            )
        shutil.move(str(source), destination)

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc).astimezone()
        return parsed

    def _require_legend(self, legend_id: int) -> dict[str, Any]:
        legend = self.database.get_legend(legend_id)
        if legend is None:
            raise KeyError(legend_id)
        return legend
