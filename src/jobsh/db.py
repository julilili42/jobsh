import sqlite3
from pathlib import Path

from .classification import classify

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
        for name, definition in (
            ("missing_imports", "INTEGER NOT NULL DEFAULT 0 CHECK (missing_imports >= 0)"),
            ("source_category", "TEXT"),
            ("classification_rule", "TEXT"),
        ):
            if name not in columns:
                database.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
        for job_id, title, description, category in database.execute(
            "SELECT id, title, description, source_category FROM jobs WHERE classification_rule IS NULL"
        ).fetchall():
            database.execute(
                "UPDATE jobs SET it_classification = ?, classification_rule = ? WHERE id = ?",
                (*classify(title, description or "", category or ""), job_id),
            )
    if not database.execute("SELECT 1 FROM sqlite_master WHERE name = 'jobs_fts'").fetchone():
        database.executescript(
            "BEGIN IMMEDIATE;\n" + MIGRATION.with_name("002_search.sql").read_text() + "\nCOMMIT;"
        )
    return database
