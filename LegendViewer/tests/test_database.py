from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from legend_viewer.database import LegendDatabase


class DatabaseMigrationTests(unittest.TestCase):
    def test_version_one_database_preserves_data_and_migrates_to_version_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legend.db"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE legends(id INTEGER PRIMARY KEY, note TEXT)")
            connection.execute("INSERT INTO legends(id, note) VALUES(1, 'keep')")
            connection.execute("PRAGMA user_version = 1")
            connection.commit()
            connection.close()

            database = LegendDatabase(path)
            try:
                columns = {
                    row[1]
                    for row in database.connection.execute("PRAGMA table_info(legends)")
                }
                version = database.connection.execute("PRAGMA user_version").fetchone()[0]
                self.assertIn("parameters_json", columns)
                self.assertIn("partner_id", columns)
                self.assertIn("is_hidden", columns)
                self.assertIn("is_favorite", columns)
                self.assertEqual(2, version)
                self.assertEqual(
                    ("keep",),
                    tuple(database.connection.execute("SELECT note FROM legends WHERE id = 1").fetchone()),
                )
            finally:
                database.close()

    def test_version_two_database_adds_missing_columns_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legend.db"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE legends(id INTEGER PRIMARY KEY, parameters_json TEXT NOT NULL DEFAULT '{}')"
            )
            connection.execute("INSERT INTO legends(id) VALUES(1)")
            connection.execute("PRAGMA user_version = 2")
            connection.commit()
            connection.close()

            database = LegendDatabase(path)
            try:
                columns = {
                    row[1]
                    for row in database.connection.execute("PRAGMA table_info(legends)")
                }
                self.assertIn("partner_id", columns)
                self.assertIn("is_hidden", columns)
                self.assertIn("is_favorite", columns)
                self.assertEqual(
                    (0, 0),
                    tuple(
                        database.connection.execute(
                            "SELECT is_hidden, is_favorite FROM legends WHERE id = 1"
                        ).fetchone()
                    ),
                )
                self.assertEqual(
                    2,
                    database.connection.execute("PRAGMA user_version").fetchone()[0],
                )
            finally:
                database.close()

            database = LegendDatabase(path)
            try:
                self.assertEqual(
                    2,
                    database.connection.execute("PRAGMA user_version").fetchone()[0],
                )
                self.assertEqual(
                    (0, 0),
                    tuple(
                        database.connection.execute(
                            "SELECT is_hidden, is_favorite FROM legends WHERE id = 1"
                        ).fetchone()
                    ),
                )
            finally:
                database.close()

    def test_known_version_three_preserves_partner_data_and_normalizes_to_version_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legend.db"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE legends(id INTEGER PRIMARY KEY, partner_id INTEGER, note TEXT)"
            )
            connection.execute("INSERT INTO legends(id, partner_id, note) VALUES(1, 42, 'keep')")
            connection.execute("PRAGMA user_version = 3")
            connection.commit()
            connection.close()

            database = LegendDatabase(path)
            try:
                columns = {
                    row[1]
                    for row in database.connection.execute("PRAGMA table_info(legends)")
                }
                self.assertIn("partner_id", columns)
                self.assertIn("is_hidden", columns)
                self.assertIn("is_favorite", columns)
                self.assertEqual(
                    (42, "keep", 0, 0),
                    tuple(
                        database.connection.execute(
                            "SELECT partner_id, note, is_hidden, is_favorite FROM legends WHERE id = 1"
                        ).fetchone()
                    ),
                )
                self.assertEqual(
                    2,
                    database.connection.execute("PRAGMA user_version").fetchone()[0],
                )
            finally:
                database.close()

    def test_new_database_uses_version_two_with_compatibility_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legend.db"
            database = LegendDatabase(path)
            try:
                columns = {
                    row[1]
                    for row in database.connection.execute("PRAGMA table_info(legends)")
                }
                self.assertIn("partner_id", columns)
                self.assertIn("is_hidden", columns)
                self.assertIn("is_favorite", columns)
                self.assertEqual(
                    2,
                    database.connection.execute("PRAGMA user_version").fetchone()[0],
                )
            finally:
                database.close()

    def test_newer_database_requests_application_update_with_exact_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legend.db"
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA user_version = 4")
            connection.commit()
            connection.close()

            with self.assertRaises(RuntimeError) as context:
                LegendDatabase(path)
            self.assertEqual(
                "アプリケーションを最新版に更新してください。",
                str(context.exception),
            )
            reopened = sqlite3.connect(path)
            try:
                self.assertEqual(4, reopened.execute("PRAGMA user_version").fetchone()[0])
            finally:
                reopened.close()
