from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .textfile import normalize_for_matching


@dataclass(frozen=True)
class TagDefinition:
    id: str
    label: str
    category: str
    order: int
    default_visible: bool
    auto_confirm: bool
    story_keys_any: tuple[str, ...]


@dataclass(frozen=True)
class EndingDefinition:
    title_id: int
    file_prefix: str
    name: str
    tag_id: str
    tag_label: str
    heroine: str | None


class Catalog:
    def __init__(self, preset_path: Path, tag_catalog_path: Path) -> None:
        with preset_path.open("r", encoding="utf-8-sig") as handle:
            preset: dict[str, Any] = json.load(handle)
        with tag_catalog_path.open("r", encoding="utf-8-sig") as handle:
            tag_catalog: dict[str, Any] = json.load(handle)

        self.preset_version = str(
            tag_catalog.get("preset_version")
            or preset["source"].get("version")
            or preset["source"]["name"]
        )
        self.tags = {
            item["id"]: TagDefinition(
                id=item["id"],
                label=item["label"],
                category=item["category"],
                order=int(item["order"]),
                default_visible=bool(item["default_visible"]),
                auto_confirm=bool(item["auto_confirm"]),
                story_keys_any=tuple(item.get("story_keys_any") or ()),
            )
            for item in tag_catalog["tags"]
        }
        self.categories = tuple(tag_catalog["categories"])
        self.system_states = tuple(tag_catalog["system_states"])
        self.future_death_tags = tuple(tag_catalog["future_death_tags"])

        self.endings: dict[int, EndingDefinition] = {}
        self.endings_by_prefix: dict[str, EndingDefinition] = {}
        self.endings_by_normalized_name: dict[str, EndingDefinition] = {}
        for item in preset["titles"]["endings"]:
            title_id = int(item["titleId"])
            ending = EndingDefinition(
                title_id=title_id,
                file_prefix=item["filePrefix"],
                name=item["jpName"],
                tag_id=f"ending.{title_id}",
                tag_label=f"{item['filePrefix']} {item['jpName']}",
                heroine=item.get("heroine"),
            )
            self.endings[title_id] = ending
            self.endings_by_prefix[ending.file_prefix.casefold()] = ending
            self.endings_by_normalized_name[normalize_for_matching(ending.name)] = ending

        legend_info = preset.get("legendInfo", [])
        legend_items = legend_info.values() if isinstance(legend_info, dict) else legend_info
        self.legend_info = {value["key"]: value["text"] for value in legend_items}

    def ordered_tags(self, include_spoilers: bool = False) -> list[TagDefinition]:
        return sorted(
            (
                tag
                for tag in self.tags.values()
                if include_spoilers or tag.default_visible
            ),
            key=lambda tag: (tag.order, tag.label),
        )

    def rule_tags_for_story_keys(self, story_keys: Iterable[str]) -> list[TagDefinition]:
        available: set[str] = set()
        for key in story_keys:
            available.add(key)
            if key.startswith("LegendInfo/"):
                available.add(key.removeprefix("LegendInfo/"))
            else:
                available.add(f"LegendInfo/{key}")

        return [
            tag
            for tag in self.tags.values()
            if tag.auto_confirm
            and tag.story_keys_any
            and any(key in available for key in tag.story_keys_any)
        ]

    def find_ending(self, title_id: int | None, file_prefix: str | None, name: str | None) -> EndingDefinition | None:
        if title_id is not None and title_id in self.endings:
            return self.endings[title_id]
        if file_prefix:
            ending = self.endings_by_prefix.get(file_prefix.casefold())
            if ending:
                return ending
        if name:
            return self.endings_by_normalized_name.get(normalize_for_matching(name))
        return None
