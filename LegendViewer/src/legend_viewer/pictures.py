from __future__ import annotations

import json
from pathlib import Path


class EndingPictureIndex:
    def __init__(self, pictures_directory: Path) -> None:
        self.pictures_directory = pictures_directory.resolve()
        self.index_path = self.pictures_directory / "index.json"

    def picture_for_title(self, title_id: int | None) -> Path | None:
        if title_id is None or not self.index_path.is_file():
            return None
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8-sig"))
            item = (payload.get("endings") or {}).get(str(title_id))
            file_name = item.get("file") if isinstance(item, dict) else None
            if not file_name or Path(file_name).name != file_name:
                return None
            candidate = (self.pictures_directory / file_name).resolve()
            candidate.relative_to(self.pictures_directory)
            return candidate if candidate.is_file() else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
