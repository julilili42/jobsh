import io
import json
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from jobsh.adapters.personio import normalize_feed
from jobsh.cli import main
from jobsh.db import MIGRATION, connect, register_source, save_jobs
from jobsh.search import get_job, search

SAMPLE = json.loads((Path(__file__).parents[1] / "testdata/search.json").read_text())
URL = "https://example.jobs.personio.de/xml"


def seed(database):
    register_source(database, "personio", "example", URL, "manual")
    source_id = database.execute("SELECT id FROM sources").fetchone()["id"]
    root = ET.Element("workzag-jobs")
    for index, item in enumerate(SAMPLE, 1):
        position = ET.SubElement(root, "position")
        for tag, value in (("id", str(index)), ("name", item["title"]),
                           ("office", item.get("location", "")),
                           ("department", item.get("category", ""))):
            ET.SubElement(position, tag).text = value
        section = ET.SubElement(ET.SubElement(position, "jobDescriptions"), "jobDescription")
        ET.SubElement(section, "value").text = item.get("description", "") + " " + item.get("mode", "")
    records = normalize_feed(ET.tostring(root), URL)
    save_jobs(database, source_id, records, "2026-09-09")
    return source_id, records


class SearchTest(unittest.TestCase):
    def test_plain_text_and_query_excerpts_preserve_source(self):
        from jobsh.text import plain_text

        self.assertEqual(plain_text("<p>C<u>#</u> &amp; Python</p><ul><li>Remote<br>in Germany</li></ul>"),
                         "C# & Python\nRemote\nin Germany")
        self.assertEqual(plain_text("SQL < 3\nPython > 2"), "SQL < 3\nPython > 2")
        self.assertIsNone(plain_text(None))
        with closing(connect(":memory:")) as database:
            seed(database)
            html = ("<style>.hidden {color:red}</style><script>ignore()</script><p>"
                    + "Company background. " * 80
                    + "</p><p>First experience with <b>Python</b> and C#. Mobile work possible.</p>"
                    + "<p>Benefits. " * 80)
            database.execute("UPDATE jobs SET description = ? WHERE id = 2", (html,))
            for query in ("Python", "C#"):
                job, = search(database, query, title="Go Developer")["jobs"]
                self.assertIn(query, job["snippet"])
                self.assertIn("Mobile work possible", job["snippet"])
                self.assertLessEqual(len(job["snippet"]), 320)
                self.assertNotIn("<", job["snippet"])
                self.assertNotIn("description", job)
            detail = get_job(database, 2)["description"]
            self.assertIn("Python and C#", detail)
            self.assertNotIn("ignore()", detail)
            self.assertNotIn("color:red", detail)
            self.assertTrue(search(database, title="Go Developer")["jobs"][0]["snippet"].startswith("Company background"))
            self.assertEqual(database.execute("SELECT description FROM jobs WHERE id = 2").fetchone()[0], html)
            database.execute("UPDATE jobs SET description = NULL WHERE id = 2")
            self.assertEqual(search(database, "Go")["jobs"][0]["snippet"], "")

    def test_composed_filters_technical_terms_and_pagination(self):
        with closing(connect(":memory:")) as database:
            seed(database)
            for query, expected in (("Go", "Go Developer"), ("C++", "C++ Developer"),
                                    ("C#", "C# Developer"), (".NET", ".NET Developer")):
                with self.subTest(query=query):
                    self.assertEqual([j["title"] for j in search(database, query)["jobs"]], [expected])
            for title in ("", "Developer"):
                for location in ("", "Berlin", "Hamburg"):
                    for mode in (None, "remote", "onsite", "hybrid"):
                        expected = [i for i, row in enumerate(SAMPLE, 1)
                                    if title.lower() in row["title"].lower()
                                    and location.lower() in row.get("location", "").lower()
                                    and (mode is None or row.get("mode", "unknown") == mode)]
                        self.assertEqual([j["id"] for j in search(database, title=title, location=location, work_mode=mode, limit=100)["jobs"]], expected)
            self.assertEqual([j["id"] for j in search(database, "Go", location="Berlin", work_mode="remote")["jobs"]], [2])
            all_ids = [j["id"] for j in search(database, limit=100)["jobs"]]
            self.assertEqual(len(all_ids), len(SAMPLE))
            paged, cursor = [], 0
            while cursor is not None:
                page = search(database, limit=3, cursor=cursor)
                paged.extend(j["id"] for j in page["jobs"])
                cursor = page["next_cursor"]
            self.assertEqual(paged, all_ids)
            self.assertIsNone(search(database, limit=len(SAMPLE))["next_cursor"])
            self.assertEqual(search(database, "Python", cursor=all_ids[-1])["jobs"], [])
            with self.assertRaises(ValueError):
                search(database, "' OR 1=1 --")
            self.assertEqual(search(database, 'Go" OR "Python')["jobs"], [])
            self.assertEqual(search(database, location="%")["jobs"], [])
            for options in ({"limit": 0}, {"limit": 101}, {"cursor": -1}, {"cursor": 2**63}, {"query": "a" * 1001}, {"location": "a" * 1001}, {"work_mode": "anything"}):
                with self.assertRaises(ValueError):
                    search(database, **options)
            detail = get_job(database, 19)
            self.assertEqual(detail["description"], "Wir verwenden moderne Software.")
            self.assertNotIn("description", search(database)["jobs"][0])
            self.assertNotIn("raw_record", detail)

    def test_index_updates_closures_and_rollback(self):
        with closing(connect(":memory:")) as database:
            with database:
                source_id, records = seed(database)
            original = get_job(database, 2)
            with self.assertRaises(RuntimeError), database:
                database.execute("UPDATE jobs SET title = 'Rust Developer' WHERE id = 2")
                raise RuntimeError("rollback")
            self.assertEqual(search(database, "Go")["jobs"][0]["id"], 2)
            database.execute("UPDATE jobs SET title = 'Rust Developer' WHERE id = 2")
            self.assertEqual(search(database, "Go")["jobs"], [])
            self.assertEqual(search(database, "Rust")["jobs"][0]["id"], 2)
            database.execute("UPDATE jobs SET closed_at = '2026-09-10' WHERE id = 2")
            self.assertEqual(search(database, "Rust")["jobs"], [])
            self.assertIsNotNone(get_job(database, 2)["closed_at"])
            save_jobs(database, source_id, [records[1]], "2026-09-11")
            self.assertEqual(search(database, "Go")["jobs"][0]["id"], original["id"])
            database.execute("DELETE FROM jobs WHERE id = 2")
            self.assertEqual(search(database, "Go")["jobs"], [])

    def test_full_text_search_keeps_umlauts_distinct(self):
        with closing(connect(":memory:")) as database:
            seed(database)
            database.execute("UPDATE jobs SET title = 'Rüst Developer' WHERE id = 2")
            self.assertEqual(search(database, "Rust")["jobs"], [])
            self.assertEqual(search(database, "Rüst")["jobs"][0]["id"], 2)

    def test_existing_full_text_index_becomes_diacritic_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            old_fts = (MIGRATION.with_name("002_search.sql").read_text().replace(
                "USING fts5(title, description, tokenize='unicode61 remove_diacritics 0');",
                "USING fts5(title, description);",
            ))
            with closing(sqlite3.connect(path)) as database:
                database.executescript(MIGRATION.read_text() + old_fts)
            with closing(connect(path)) as database:
                self.assertIn("remove_diacritics 0", database.execute(
                    "SELECT sql FROM sqlite_master WHERE name = 'jobs_fts'"
                ).fetchone()[0])

    def test_long_title_and_location_filters_follow_updates(self):
        with closing(connect(":memory:")) as database:
            seed(database)
            self.assertEqual([job["id"] for job in search(database, title="Go Developer")["jobs"]], [2])
            self.assertIn(2, [job["id"] for job in search(database, location="Berlin")["jobs"]])
            database.execute("UPDATE jobs SET location_text = 'Munich, Germany' WHERE id = 2")
            self.assertEqual([job["id"] for job in search(database, location="Munich")["jobs"]], [2])
            self.assertNotIn(2, [job["id"] for job in search(database, location="Berlin")["jobs"]])
            database.execute("UPDATE jobs SET title = 'Rust Developer' WHERE id = 2")
            self.assertEqual(search(database, title="Go Developer")["jobs"], [])
            self.assertEqual([job["id"] for job in search(database, title="Rust Developer")["jobs"]], [2])

    def test_cli_json_and_missing_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            with closing(connect(path)) as database, database:
                seed(database)
            for command in (["search", "Go", "--json"], ["show", "2", "--json"]):
                out, err = io.StringIO(), io.StringIO()
                with patch("sys.argv", ["jobsh", "--db", str(path), *command]), redirect_stdout(out), redirect_stderr(err):
                    main()
                result = json.loads(out.getvalue())
                self.assertEqual((result["jobs"][0] if "jobs" in result else result)["id"], 2)
                self.assertEqual(err.getvalue(), "")
            for command in (["show", "999", "--json"], ["show", "0"], ["search", "--limit", "101"], ["nonsense"]):
                out, err = io.StringIO(), io.StringIO()
                with patch("sys.argv", ["jobsh", "--db", str(path), *command]), \
                        redirect_stdout(out), redirect_stderr(err), \
                        self.assertRaises(SystemExit) as error:
                    main()
                self.assertNotEqual(error.exception.code, 0)
                self.assertEqual(out.getvalue(), "")
                self.assertTrue(err.getvalue())

    def test_legacy_jobs_remain_searchable_without_reclassification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            with closing(sqlite3.connect(path)) as database, database:
                database.executescript(MIGRATION.read_text().replace("    source_category TEXT,\n", ""))
                database.execute("ALTER TABLE jobs ADD COLUMN it_classification TEXT DEFAULT 'non_it'")
                database.execute("ALTER TABLE jobs ADD COLUMN german_eligibility TEXT DEFAULT 'ineligible'")
                register_source(database, "personio", "example", URL, "manual")
                database.execute(
                    "INSERT INTO jobs (source_id, external_id, title, locations, work_mode, "
                    "location_text, original_url, first_seen_at, last_seen_at, content_hash, raw_record) "
                    "VALUES (1, '1', 'Go Developer', '[]', 'remote', 'Paris, France', ?, "
                    "'first', 'last', 'hash', '<position/>')", (URL,),
                )
            for _ in range(2):
                with closing(connect(path)) as database:
                    job, = search(database, "Go")["jobs"]
                    self.assertEqual(job["id"], 1)
                    self.assertNotIn("it_classification", get_job(database, 1))
                    self.assertEqual(tuple(database.execute(
                        "SELECT id, first_seen_at, content_hash, it_classification FROM jobs"
                    ).fetchone()), (1, "first", "hash", "non_it"))
