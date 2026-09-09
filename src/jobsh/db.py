import sqlite3
from pathlib import Path

MIGRATION = Path(__file__).parents[2] / "migrations" / "001_initial.sql"


def connect(path: str | Path) -> sqlite3.Connection:
    database = sqlite3.connect(path)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    database.execute("PRAGMA journal_mode = WAL")
    database.executescript(MIGRATION.read_text())
    with database:
        database.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in database.execute("PRAGMA table_info(jobs)")}
        if "missing_imports" not in columns:
            database.execute(
                "ALTER TABLE jobs ADD COLUMN missing_imports INTEGER NOT NULL "
                "DEFAULT 0 CHECK (missing_imports >= 0)"
            )
    return database
