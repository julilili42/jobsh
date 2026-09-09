import sqlite3
from pathlib import Path

MIGRATION = Path(__file__).parents[2] / "migrations" / "001_initial.sql"


def connect(path: str | Path) -> sqlite3.Connection:
    database = sqlite3.connect(path)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    database.execute("PRAGMA journal_mode = WAL")
    database.executescript(MIGRATION.read_text())
    return database
