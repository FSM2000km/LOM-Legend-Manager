from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .catalog import Catalog, EndingDefinition, TagDefinition


METADATA_SOURCE_PRIORITY = {
    "unknown": 0,
    "filename": 10,
    "text_inference": 20,
    "ending_preset": 25,
    "story_rule": 30,
    "game_end_key": 30,
    "game_title_partner": 30,
    "manual": 40,
}
CONFIDENCE_PRIORITY = {
    "low": 0,
    "partial": 10,
    "filename": 20,
    "exact": 30,
    "manual": 40,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LegendDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=5.0)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA journal_mode = DELETE")
        self.connection.execute("PRAGMA synchronous = FULL")
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "LegendDatabase":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _migrate(self) -> None:
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if version > 2:
            raise RuntimeError(f"未対応のDBスキーマです: {version}")
        if version == 2:
            return
        if version == 1:
            with self.transaction() as connection:
                connection.execute(
                    "ALTER TABLE legends ADD COLUMN parameters_json TEXT NOT NULL DEFAULT '{}'"
                )
                connection.execute("PRAGMA user_version = 2")
            return

        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE legends (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_event_id TEXT UNIQUE,
                    content_sha256 TEXT NOT NULL,
                    normalized_sha256 TEXT NOT NULL,
                    file_sha256 TEXT NOT NULL,
                    hash8 TEXT NOT NULL,
                    original_file_name TEXT NOT NULL,
                    current_file_name TEXT NOT NULL,
                    full_path TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    exported_at TEXT,
                    file_size INTEGER NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'ending',
                    title_id INTEGER,
                    file_prefix TEXT,
                    title_name TEXT,
                    title_source TEXT NOT NULL DEFAULT 'unknown',
                    heroine_id INTEGER,
                    heroine TEXT,
                    heroine_source TEXT NOT NULL DEFAULT 'unknown',
                    end_key TEXT,
                    slot INTEGER,
                    confidence TEXT NOT NULL DEFAULT 'low',
                    duplicate_of INTEGER REFERENCES legends(id) ON DELETE SET NULL,
                    note TEXT NOT NULL DEFAULT '',
                    story_keys_json TEXT NOT NULL DEFAULT '[]',
                    story_key_sha256 TEXT,
                    parameters_json TEXT NOT NULL DEFAULT '{}',
                    tags_embedded_at TEXT,
                    file_missing INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX legends_content_hash_idx ON legends(content_sha256);
                CREATE INDEX legends_title_idx ON legends(title_id);
                CREATE INDEX legends_heroine_idx ON legends(heroine);
                CREATE INDEX legends_exported_at_idx ON legends(exported_at DESC);

                CREATE TABLE legend_text (
                    legend_id INTEGER PRIMARY KEY REFERENCES legends(id) ON DELETE CASCADE,
                    plain_text TEXT NOT NULL
                );

                CREATE TABLE tags (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    category TEXT NOT NULL,
                    default_visible INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 999999,
                    source_catalog INTEGER NOT NULL DEFAULT 1,
                    is_spoiler INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX tags_category_order_idx ON tags(category, sort_order);

                CREATE TABLE legend_tags (
                    legend_id INTEGER NOT NULL REFERENCES legends(id) ON DELETE CASCADE,
                    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    is_confirmed INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (legend_id, tag_id)
                );

                CREATE TABLE tag_suppressions (
                    legend_id INTEGER NOT NULL REFERENCES legends(id) ON DELETE CASCADE,
                    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (legend_id, tag_id)
                );

                CREATE TABLE audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    legend_id INTEGER REFERENCES legends(id) ON DELETE SET NULL,
                    action TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                PRAGMA user_version = 2;
                """
            )
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES('created_at', ?)",
                (utc_now(),),
            )

    def sync_catalog(self, catalog: Catalog) -> None:
        with self.transaction() as connection:
            for tag in catalog.tags.values():
                connection.execute(
                    """
                    INSERT INTO tags(id, label, category, default_visible, sort_order, source_catalog, is_spoiler)
                    VALUES(?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        label = excluded.label,
                        category = excluded.category,
                        default_visible = excluded.default_visible,
                        sort_order = excluded.sort_order,
                        source_catalog = 1,
                        is_spoiler = excluded.is_spoiler
                    """,
                    (
                        tag.id,
                        tag.label,
                        tag.category,
                        int(tag.default_visible),
                        tag.order,
                        int(not tag.default_visible),
                    ),
                )
            connection.execute(
                """
                INSERT INTO schema_meta(key, value) VALUES('preset_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (catalog.preset_version,),
            )

    def upsert_legend(self, record: dict[str, Any], body_text: str) -> int:
        now = utc_now()
        source_event_id = record.get("source_event_id")
        full_path = str(Path(record["full_path"]).resolve())

        with self.transaction() as connection:
            existing = None
            if source_event_id:
                existing = connection.execute(
                    "SELECT * FROM legends WHERE source_event_id = ?",
                    (source_event_id,),
                ).fetchone()
            if existing is None:
                existing = connection.execute(
                    "SELECT * FROM legends WHERE full_path = ? COLLATE NOCASE",
                    (full_path,),
                ).fetchone()
            if existing is None and str(source_event_id or "").startswith("scan."):
                relocated = connection.execute(
                    """
                    SELECT * FROM legends
                    WHERE content_sha256 = ? AND file_missing = 1
                    ORDER BY id
                    """,
                    (record["content_sha256"],),
                ).fetchall()
                if len(relocated) == 1:
                    existing = relocated[0]

            values = {
                "source_event_id": source_event_id,
                "content_sha256": record["content_sha256"],
                "normalized_sha256": record["normalized_sha256"],
                "file_sha256": record["file_sha256"],
                "hash8": record["content_sha256"][:8],
                "original_file_name": record["original_file_name"],
                "current_file_name": Path(full_path).name,
                "full_path": full_path,
                "exported_at": record.get("exported_at"),
                "file_size": int(record["file_size"]),
                "kind": record.get("kind") or "ending",
                "title_id": record.get("title_id"),
                "file_prefix": record.get("file_prefix"),
                "title_name": record.get("title_name"),
                "title_source": record.get("title_source") or "unknown",
                "heroine_id": record.get("heroine_id"),
                "heroine": record.get("heroine"),
                "heroine_source": record.get("heroine_source") or "unknown",
                "end_key": record.get("end_key"),
                "slot": record.get("slot"),
                "confidence": record.get("confidence") or "low",
                "story_keys_json": json.dumps(record.get("story_keys") or [], ensure_ascii=False),
                "story_key_sha256": record.get("story_key_sha256"),
                "parameters_json": json.dumps(
                    record.get("parameters") or {}, ensure_ascii=False
                ),
            }

            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO legends(
                        source_event_id, content_sha256, normalized_sha256, file_sha256, hash8,
                        original_file_name, current_file_name, full_path, exported_at, file_size,
                        kind, title_id, file_prefix, title_name, title_source,
                        heroine_id, heroine, heroine_source, end_key, slot, confidence,
                        story_keys_json, story_key_sha256, parameters_json, created_at, updated_at
                    ) VALUES(
                        :source_event_id, :content_sha256, :normalized_sha256, :file_sha256, :hash8,
                        :original_file_name, :current_file_name, :full_path, :exported_at, :file_size,
                        :kind, :title_id, :file_prefix, :title_name, :title_source,
                        :heroine_id, :heroine, :heroine_source, :end_key, :slot, :confidence,
                        :story_keys_json, :story_key_sha256, :parameters_json, :created_at, :updated_at
                    )
                    """,
                    {**values, "created_at": now, "updated_at": now},
                )
                legend_id = int(cursor.lastrowid)
            else:
                legend_id = int(existing["id"])
                if self._source_priority(existing["title_source"]) > self._source_priority(
                    values["title_source"]
                ):
                    for key in ("title_id", "file_prefix", "title_name", "title_source"):
                        values[key] = existing[key]
                if self._source_priority(existing["heroine_source"]) > self._source_priority(
                    values["heroine_source"]
                ):
                    for key in ("heroine_id", "heroine", "heroine_source"):
                        values[key] = existing[key]
                if self._confidence_priority(existing["confidence"]) > self._confidence_priority(
                    values["confidence"]
                ):
                    values["confidence"] = existing["confidence"]

                existing_event_id = existing["source_event_id"]
                incoming_event_id = values["source_event_id"]
                if (
                    existing_event_id
                    and not str(existing_event_id).startswith("scan.")
                    and (not incoming_event_id or str(incoming_event_id).startswith("scan."))
                ):
                    values["source_event_id"] = existing_event_id

                incoming_story_keys = json.loads(values["story_keys_json"])
                existing_story_keys = json.loads(existing["story_keys_json"] or "[]")
                if not incoming_story_keys and existing_story_keys:
                    values["story_keys_json"] = existing["story_keys_json"]
                incoming_parameters = json.loads(values["parameters_json"])
                existing_parameters = json.loads(existing["parameters_json"] or "{}")
                if not incoming_parameters and existing_parameters:
                    values["parameters_json"] = existing["parameters_json"]
                values["id"] = legend_id
                values["updated_at"] = now
                connection.execute(
                    """
                    UPDATE legends SET
                        source_event_id = COALESCE(:source_event_id, source_event_id),
                        content_sha256 = :content_sha256,
                        normalized_sha256 = :normalized_sha256,
                        file_sha256 = :file_sha256,
                        hash8 = :hash8,
                        original_file_name = :original_file_name,
                        current_file_name = :current_file_name,
                        full_path = :full_path,
                        exported_at = COALESCE(:exported_at, exported_at),
                        file_size = :file_size,
                        kind = :kind,
                        title_id = :title_id,
                        file_prefix = :file_prefix,
                        title_name = :title_name,
                        title_source = :title_source,
                        heroine_id = :heroine_id,
                        heroine = :heroine,
                        heroine_source = :heroine_source,
                        end_key = COALESCE(:end_key, end_key),
                        slot = COALESCE(:slot, slot),
                        confidence = :confidence,
                        story_keys_json = :story_keys_json,
                        story_key_sha256 = COALESCE(:story_key_sha256, story_key_sha256),
                        parameters_json = :parameters_json,
                        file_missing = 0,
                        updated_at = :updated_at
                    WHERE id = :id
                    """,
                    values,
                )

            connection.execute(
                """
                INSERT INTO legend_text(legend_id, plain_text) VALUES(?, ?)
                ON CONFLICT(legend_id) DO UPDATE SET plain_text = excluded.plain_text
                """,
                (legend_id, body_text),
            )
        return legend_id

    @staticmethod
    def _source_priority(source: str | None) -> int:
        return METADATA_SOURCE_PRIORITY.get(source or "unknown", 0)

    @staticmethod
    def _confidence_priority(confidence: str | None) -> int:
        return CONFIDENCE_PRIORITY.get(confidence or "low", 0)

    def replace_automatic_tags(
        self,
        legend_id: int,
        assignments: Iterable[tuple[str, str, str]],
    ) -> None:
        now = utc_now()
        assignments = list(dict.fromkeys(assignments))
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM legend_tags WHERE legend_id = ? AND source <> 'manual' AND source <> 'manual_metadata'",
                (legend_id,),
            )
            protected_categories = {
                str(row["category"])
                for row in connection.execute(
                    """
                    SELECT DISTINCT t.category
                    FROM legend_tags lt
                    JOIN tags t ON t.id = lt.tag_id
                    WHERE lt.legend_id = ? AND lt.source = 'manual_metadata'
                    """,
                    (legend_id,),
                ).fetchall()
            }
            for tag_id, source, confidence in assignments:
                category_row = connection.execute(
                    "SELECT category FROM tags WHERE id = ?", (tag_id,)
                ).fetchone()
                if category_row is None:
                    continue
                if str(category_row["category"]) in protected_categories:
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO legend_tags(legend_id, tag_id, source, confidence, is_confirmed, created_at)
                    SELECT ?, ?, ?, ?, 1, ?
                    WHERE NOT EXISTS(
                        SELECT 1 FROM tag_suppressions WHERE legend_id = ? AND tag_id = ?
                    )
                    """,
                    (legend_id, tag_id, source, confidence, now, legend_id, tag_id),
                )

    def set_automatic_relationship(
        self,
        legend_id: int,
        heroine_id: int | None,
        heroine: str | None,
        source: str,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE legends SET
                    heroine_id = ?, heroine = ?, heroine_source = ?, updated_at = ?
                WHERE id = ? AND heroine_source <> 'manual'
                """,
                (heroine_id, heroine, source, utc_now(), legend_id),
            )

    def list_legends(
        self,
        query: str = "",
        category: str | None = None,
        directory: Path | None = None,
        title_ids: set[int | None] | None = None,
        heroine_ids: set[int | None] | None = None,
        tag_ids: set[str] | None = None,
        require_all_tags: bool = True,
    ) -> list[sqlite3.Row]:
        pattern = f"%{query.strip()}%"
        parameters: list[Any] = [pattern, pattern, pattern, pattern, pattern]
        category_clause = ""
        if category:
            category_clause = """
                AND EXISTS(
                    SELECT 1 FROM legend_tags filter_lt
                    JOIN tags filter_t ON filter_t.id = filter_lt.tag_id
                    WHERE filter_lt.legend_id = l.id AND filter_t.category = ?
                )
            """
            parameters.append(category)
        directory_clause = ""
        if directory is not None:
            root = str(directory.resolve()).rstrip("\\/") + os.sep
            directory_clause = """
                AND substr(lower(l.full_path), 1, length(?)) = lower(?)
            """
            parameters.extend((root, root))

        metadata_clauses: list[str] = []
        for column, selected in (("l.title_id", title_ids), ("l.heroine_id", heroine_ids)):
            if not selected:
                continue
            values = [value for value in selected if value is not None]
            parts: list[str] = []
            if values:
                parts.append(f"{column} IN ({','.join('?' for _ in values)})")
                parameters.extend(values)
            if None in selected:
                parts.append(f"{column} IS NULL")
            metadata_clauses.append("AND (" + " OR ".join(parts) + ")")

        tag_clause = ""
        if tag_ids:
            placeholders = ",".join("?" for _ in tag_ids)
            if require_all_tags:
                tag_clause = f"""
                    AND (
                        SELECT COUNT(DISTINCT selected_lt.tag_id)
                        FROM legend_tags selected_lt
                        WHERE selected_lt.legend_id = l.id
                          AND selected_lt.is_confirmed = 1
                          AND selected_lt.tag_id IN ({placeholders})
                    ) = ?
                """
                parameters.extend(sorted(tag_ids))
                parameters.append(len(tag_ids))
            else:
                tag_clause = f"""
                    AND EXISTS(
                        SELECT 1 FROM legend_tags selected_lt
                        WHERE selected_lt.legend_id = l.id
                          AND selected_lt.is_confirmed = 1
                          AND selected_lt.tag_id IN ({placeholders})
                    )
                """
                parameters.extend(sorted(tag_ids))

        return self.connection.execute(
            f"""
            SELECT
                l.*,
                CASE WHEN l.duplicate_of IS NULL THEN 0 ELSE 1 END AS is_duplicate,
                GROUP_CONCAT(
                    CASE WHEN t.category NOT IN ('ending', 'heroine') THEN t.label END,
                    ' / '
                ) AS tag_labels
            FROM legends l
            LEFT JOIN legend_text tx ON tx.legend_id = l.id
            LEFT JOIN legend_tags lt ON lt.legend_id = l.id AND lt.is_confirmed = 1
            LEFT JOIN tags t ON t.id = lt.tag_id
            WHERE (
                ? = '%%'
                OR l.current_file_name LIKE ?
                OR COALESCE(l.title_name, '') LIKE ?
                OR COALESCE(l.heroine, '') LIKE ?
                OR COALESCE(tx.plain_text, '') LIKE ?
            )
            {category_clause}
            {directory_clause}
            {' '.join(metadata_clauses)}
            {tag_clause}
            GROUP BY l.id
            ORDER BY COALESCE(l.exported_at, l.created_at) DESC, l.id DESC
            """,
            parameters,
        ).fetchall()

    def get_legend(self, legend_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT l.*, tx.plain_text
            FROM legends l
            LEFT JOIN legend_text tx ON tx.legend_id = l.id
            WHERE l.id = ?
            """,
            (legend_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        try:
            result["parameters"] = json.loads(result.get("parameters_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            result["parameters"] = {}
        result["tags"] = [
            dict(tag)
            for tag in self.connection.execute(
                """
                SELECT t.*, lt.source, lt.confidence, lt.is_confirmed
                FROM legend_tags lt
                JOIN tags t ON t.id = lt.tag_id
                WHERE lt.legend_id = ?
                ORDER BY t.sort_order, t.label
                """,
                (legend_id,),
            ).fetchall()
        ]
        return result

    def get_available_tags(self, include_spoilers: bool = False) -> list[sqlite3.Row]:
        clause = "" if include_spoilers else "WHERE is_spoiler = 0"
        return self.connection.execute(
            f"SELECT * FROM tags {clause} ORDER BY sort_order, label"
        ).fetchall()

    def get_assigned_tags(self, include_spoilers: bool = False) -> list[sqlite3.Row]:
        spoiler_clause = "" if include_spoilers else "AND t.is_spoiler = 0"
        return self.connection.execute(
            f"""
            SELECT t.*, COUNT(DISTINCT lt.legend_id) AS legend_count
            FROM tags t
            JOIN legend_tags lt ON lt.tag_id = t.id AND lt.is_confirmed = 1
            WHERE 1 = 1 {spoiler_clause}
            GROUP BY t.id
            ORDER BY t.sort_order, t.label
            """
        ).fetchall()

    def add_manual_tag(self, legend_id: int, tag_id: str) -> None:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM tag_suppressions WHERE legend_id = ? AND tag_id = ?",
                (legend_id, tag_id),
            )
            connection.execute(
                """
                INSERT INTO legend_tags(legend_id, tag_id, source, confidence, is_confirmed, created_at)
                VALUES(?, ?, 'manual', 'user', 1, ?)
                ON CONFLICT(legend_id, tag_id) DO UPDATE SET
                    source = 'manual', confidence = 'user', is_confirmed = 1
                """,
                (legend_id, tag_id, now),
            )
            self._audit(connection, legend_id, "tag_added", {"tag_id": tag_id})

    def add_freeform_tag(self, legend_id: int, label: str) -> str:
        clean_label = label.strip()
        if not clean_label:
            raise ValueError("タグ名が空です。")
        tag_id = "manual." + hashlib.sha256(clean_label.encode("utf-8")).hexdigest()[:12]
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO tags(id, label, category, default_visible, sort_order, source_catalog, is_spoiler)
                VALUES(?, ?, 'manual', 1, 8000, 0, 0)
                """,
                (tag_id, clean_label),
            )
        self.add_manual_tag(legend_id, tag_id)
        return tag_id

    def remove_tag(self, legend_id: int, tag_id: str) -> None:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM legend_tags WHERE legend_id = ? AND tag_id = ?",
                (legend_id, tag_id),
            )
            connection.execute(
                "INSERT OR REPLACE INTO tag_suppressions(legend_id, tag_id, created_at) VALUES(?, ?, ?)",
                (legend_id, tag_id, now),
            )
            self._audit(connection, legend_id, "tag_removed", {"tag_id": tag_id})

    def set_metadata(
        self,
        legend_id: int,
        ending: EndingDefinition | None,
        heroine_id: int | None,
        heroine: str | None,
        heroine_tag_id: str | None,
    ) -> None:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE legends SET
                    title_id = ?, file_prefix = ?, title_name = ?, title_source = 'manual',
                    heroine_id = ?, heroine = ?, heroine_source = 'manual',
                    confidence = 'manual', updated_at = ?
                WHERE id = ?
                """,
                (
                    ending.title_id if ending else None,
                    ending.file_prefix if ending else None,
                    ending.name if ending else None,
                    heroine_id,
                    heroine,
                    now,
                    legend_id,
                ),
            )
            connection.execute(
                """
                DELETE FROM legend_tags
                WHERE legend_id = ? AND tag_id IN (
                    SELECT id FROM tags WHERE category IN ('ending', 'heroine')
                )
                """,
                (legend_id,),
            )
            if ending:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO legend_tags(legend_id, tag_id, source, confidence, is_confirmed, created_at)
                    VALUES(?, ?, 'manual_metadata', 'user', 1, ?)
                    """,
                    (legend_id, ending.tag_id, now),
                )
            if heroine is not None:
                if heroine_tag_id is None:
                    raise ValueError("ヒロインタグIDがありません。")
                connection.execute(
                    """
                    INSERT OR REPLACE INTO legend_tags(legend_id, tag_id, source, confidence, is_confirmed, created_at)
                    VALUES(?, ?, 'manual_metadata', 'user', 1, ?)
                    """,
                    (legend_id, heroine_tag_id, now),
                )
            self._audit(
                connection,
                legend_id,
                "metadata_updated",
                {"title_id": ending.title_id if ending else None, "heroine_id": heroine_id},
            )

    def update_note(self, legend_id: int, note: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE legends SET note = ?, updated_at = ? WHERE id = ?",
                (note, utc_now(), legend_id),
            )

    def confirmed_tag_labels(self, legend_id: int) -> list[str]:
        return [
            str(row["label"])
            for row in self.connection.execute(
                """
                SELECT t.label
                FROM legend_tags lt
                JOIN tags t ON t.id = lt.tag_id
                WHERE lt.legend_id = ? AND lt.is_confirmed = 1
                ORDER BY t.sort_order, t.label
                """,
                (legend_id,),
            ).fetchall()
        ]

    def update_file_state(
        self,
        legend_id: int,
        *,
        full_path: Path | None = None,
        file_sha256: str | None = None,
        file_size: int | None = None,
        tags_embedded_at: str | None = None,
    ) -> None:
        row = self.connection.execute("SELECT * FROM legends WHERE id = ?", (legend_id,)).fetchone()
        if row is None:
            raise KeyError(legend_id)
        new_path = full_path.resolve() if full_path else Path(row["full_path"])
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE legends SET
                    current_file_name = ?, full_path = ?,
                    file_sha256 = COALESCE(?, file_sha256),
                    file_size = COALESCE(?, file_size),
                    tags_embedded_at = COALESCE(?, tags_embedded_at),
                    file_missing = 0, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_path.name,
                    str(new_path),
                    file_sha256,
                    file_size,
                    tags_embedded_at,
                    utc_now(),
                    legend_id,
                ),
            )

    def recompute_duplicates(self) -> None:
        with self.transaction() as connection:
            connection.execute("UPDATE legends SET duplicate_of = NULL")
            groups = connection.execute(
                """
                SELECT content_sha256, MIN(id) AS canonical_id
                FROM legends
                GROUP BY content_sha256
                HAVING COUNT(*) > 1
                """
            ).fetchall()
            for group in groups:
                connection.execute(
                    """
                    UPDATE legends SET duplicate_of = ?
                    WHERE content_sha256 = ? AND id <> ?
                    """,
                    (group["canonical_id"], group["content_sha256"], group["canonical_id"]),
                )

    def mark_missing_files(self) -> None:
        rows = self.connection.execute("SELECT id, full_path FROM legends").fetchall()
        with self.transaction() as connection:
            for row in rows:
                connection.execute(
                    "UPDATE legends SET file_missing = ? WHERE id = ?",
                    (int(not Path(row["full_path"]).exists()), row["id"]),
                )

    def backup(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination) as target:
            self.connection.backup(target)

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        legend_id: int | None,
        action: str,
        details: dict[str, Any],
    ) -> None:
        connection.execute(
            "INSERT INTO audit_log(legend_id, action, details_json, created_at) VALUES(?, ?, ?, ?)",
            (legend_id, action, json.dumps(details, ensure_ascii=False), utc_now()),
        )
