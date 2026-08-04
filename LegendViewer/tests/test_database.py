from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from legend_viewer.database import LegendDatabase


class DatabaseMigrationTests(unittest.TestCase):
    def test_version_one_database_adds_parameter_snapshot_column(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legend.db"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE legends(id INTEGER PRIMARY KEY)")
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
                self.assertEqual(2, version)
            finally:
                database.close()
