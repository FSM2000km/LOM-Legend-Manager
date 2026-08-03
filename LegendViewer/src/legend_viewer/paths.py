from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


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

    @classmethod
    def discover(cls) -> "AppPaths":
        if getattr(sys, "frozen", False):
            viewer_root = Path(sys.executable).resolve().parent
            resource_root = Path(getattr(sys, "_MEIPASS", viewer_root)) / "legend_data"
        else:
            package_path = Path(__file__).resolve()
            viewer_root = package_path.parents[2]
            resource_root = viewer_root.parent / "LegendManager" / "data"
        game_root = viewer_root.parent

        user_profile = Path(os.environ.get("USERPROFILE", Path.home()))
        persistent_root = user_profile / "AppData" / "LocalLow" / "Obb Studio" / "Mortal"
        manager_directory = persistent_root / "LegendManager"

        return cls(
            game_root=game_root,
            persistent_root=persistent_root,
            legend_directory=persistent_root / "Legend",
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
        ):
            directory.mkdir(parents=True, exist_ok=True)
