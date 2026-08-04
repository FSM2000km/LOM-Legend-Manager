from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def default_persistent_root() -> Path:
    user_profile = Path(os.environ.get("USERPROFILE", Path.home()))
    return user_profile / "AppData" / "LocalLow" / "Obb Studio" / "Mortal"


def is_game_root(path: Path) -> bool:
    return (
        (path / "Mortal.exe").is_file()
        and (path / "BepInEx" / "plugins").is_dir()
        and (path / "BepInEx" / "config").is_dir()
    )


def read_shared_settings(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            return {}
        return {
            key: str(value)
            for key, value in payload.items()
            if key in ("game_root", "legend_directory") and isinstance(value, str)
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def write_shared_settings(path: Path, game_root: Path, legend_directory: Path) -> None:
    payload = {
        "schema_version": 1,
        "game_root": str(game_root.resolve()),
        "legend_directory": str(legend_directory.resolve()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def ensure_writable_directory(path: Path) -> Path:
    resolved = path.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    marker: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=resolved,
            prefix=".lom_write_test.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(b"ok")
            temporary.flush()
            os.fsync(temporary.fileno())
            marker = Path(temporary.name)
    finally:
        if marker is not None:
            marker.unlink(missing_ok=True)
    return resolved


def discover_game_root(viewer_root: Path, configured: str | None = None) -> Path:
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(viewer_root.parent)

    steam_roots: list[Path] = []
    for environment_name in ("ProgramFiles(x86)", "ProgramFiles"):
        value = os.environ.get(environment_name)
        if value:
            steam_roots.append(Path(value) / "Steam")

    try:
        import winreg

        for key_path in (r"SOFTWARE\WOW6432Node\Valve\Steam", r"SOFTWARE\Valve\Steam"):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    steam_roots.append(Path(winreg.QueryValueEx(key, "InstallPath")[0]))
            except OSError:
                continue
    except ImportError:
        pass

    library_pattern = re.compile(r'^\s*"path"\s+"(?P<path>.+)"\s*$')
    for steam_root in list(dict.fromkeys(steam_roots)):
        candidates.append(steam_root / "steamapps" / "common" / "LegendOfMortal")
        library_file = steam_root / "steamapps" / "libraryfolders.vdf"
        try:
            lines = library_file.read_text(
                encoding="utf-8-sig", errors="replace"
            ).splitlines()
        except OSError:
            continue
        for line in lines:
            match = library_pattern.match(line)
            if match:
                library_root = Path(match.group("path").replace(r"\\", "\\"))
                candidates.append(
                    library_root / "steamapps" / "common" / "LegendOfMortal"
                )

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if is_game_root(resolved):
            return resolved
    return viewer_root.parent.resolve()
