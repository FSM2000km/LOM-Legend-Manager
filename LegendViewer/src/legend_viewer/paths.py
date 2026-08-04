from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .path_settings import (
    default_persistent_root,
    discover_game_root,
    ensure_writable_directory,
    read_shared_settings,
)


@dataclass(frozen=True)
class AppPaths:
    game_root: Path
    persistent_root: Path
    legend_directory: Path
    manager_directory: Path
    inbox_directory: Path
    processed_directory: Path
    failed_directory: Path
    database_path: Path
    preset_path: Path
    tag_catalog_path: Path

    @property
    def pictures_directory(self) -> Path:
        return self.legend_directory / "Pictures"

    @property
    def viewer_settings_path(self) -> Path:
        return self.manager_directory / "viewer.ini"

    @property
    def shared_settings_path(self) -> Path:
        return self.manager_directory / "settings.json"

    @classmethod
    def discover(cls) -> "AppPaths":
        if getattr(sys, "frozen", False):
            viewer_root = Path(sys.executable).resolve().parent
            resource_root = Path(getattr(sys, "_MEIPASS", viewer_root)) / "legend_data"
        else:
            package_path = Path(__file__).resolve()
            viewer_root = package_path.parents[2]
            resource_root = viewer_root.parent / "LegendManager" / "data"
        persistent_root = default_persistent_root()
        manager_directory = persistent_root / "LegendManager"
        shared_settings = read_shared_settings(manager_directory / "settings.json")
        game_root = discover_game_root(viewer_root, shared_settings.get("game_root"))
        configured_legend = shared_settings.get("legend_directory")
        standard_legend_directory = persistent_root / "Legend"
        legend_directory = standard_legend_directory
        if configured_legend:
            try:
                legend_directory = ensure_writable_directory(Path(configured_legend))
            except OSError:
                # Keep settings.json unchanged so a temporarily unavailable drive can recover.
                legend_directory = standard_legend_directory

        return cls(
            game_root=game_root,
            persistent_root=persistent_root,
            legend_directory=legend_directory,
            manager_directory=manager_directory,
            inbox_directory=manager_directory / "inbox",
            processed_directory=manager_directory / "processed",
            failed_directory=manager_directory / "failed",
            database_path=manager_directory / "legend_manager.db",
            preset_path=resource_root / "jp_v2_4_presets.json",
            tag_catalog_path=resource_root / "tags_catalog.json",
        )

    def ensure_directories(self) -> None:
        for directory in (
            self.legend_directory,
            self.manager_directory,
            self.inbox_directory,
            self.processed_directory,
            self.failed_directory,
            self.pictures_directory,
        ):
            directory.mkdir(parents=True, exist_ok=True)
