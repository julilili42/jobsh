import io
import json
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import closing, redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from jobsh.cli import main
from jobsh.db import MIGRATION, connect
from jobsh.jobs import classify, save_jobs
from jobsh.personio_feed import normalize_feed
from jobsh.search import get_job, search
from jobsh.sources import register_source

SAMPLE = json.loads((Path(__file__).parents[1] / "testdata/classification.json").read_text())
URL = "https://example.jobs.personio.de/xml"


def seed(database):
    register_source(database, "personio", "example", URL, "manual")
    source_id = database.execute("SELECT id FROM sources").fetchone()["id"]
    root = ET.Element("workzag-jobs")
    for index, item in enumerate(SAMPLE, 1):
        position = ET.SubElement(root, "position")
        for tag, value in (("id", str(index)), ("name", item["title"]),
                           ("office", item.get("location", "")), ("department", item.get("category", ""))):
            ET.SubElement(position, tag).text = value
        section = ET.SubElement(ET.SubElement(position, "jobDescriptions"), "jobDescription")
        ET.SubElement(section, "value").text = item.get("description", "") + " " + item.get("mode", "")
    records = normalize_feed(ET.tostring(root), URL)
    save_jobs(database, source_id, records, "2026-09-09")
    return source_id, records


class SearchTest(unittest.TestCase):
    def test_labeled_classifier_sample(self):
        for item in SAMPLE:
            with self.subTest(title=item["title"]):
                actual, rule = classify(item["title"], item.get("description", ""), item.get("category", ""))
                self.assertEqual(actual, item["expected"])
                self.assertTrue(rule)

    def test_composed_filters_technical_terms_and_pagination(self):
        with closing(connect(":memory:")) as database:
            seed(database)
            for query, expected in (("Go", "Go Developer"), ("C++", "C++ Developer"),
                                    ("C#", "C# Developer"), (".NET", ".NET Developer")):
                with self.subTest(query=query):
                    self.assertEqual([j["title"] for j in search(database, query)], [expected])
            for title in ("", "Developer"):
                for location in ("", "Berlin", "Hamburg"):
                    for mode in (None, "remote", "onsite", "hybrid"):
                        expected = [i for i, row in enumerate(SAMPLE, 1)
                                    if row["expected"] == "it" and title.lower() in row["title"].lower()
                                    and location.lower() in row.get("location", "").lower()
                                    and (mode is None or row.get("mode", "unknown") == mode)]
                        self.assertEqual([j["id"] for j in search(database, title=title, location=location, work_mode=mode)], expected)
            self.assertEqual([j["id"] for j in search(database, "Go", location="Berlin", work_mode="remote")], [2])
            all_ids = [j["id"] for j in search(database)]
            paged = [j["id"] for offset in range(0, len(all_ids), 3) for j in search(database, limit=3, offset=offset)]
            self.assertEqual(paged, all_ids)
            with self.assertRaises(ValueError):
                search(database, "' OR 1=1 --")
            self.assertEqual(search(database, 'Go" OR "Python'), [])
            self.assertEqual(search(database, location="%"), [])
            for options in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"work_mode": "anything"}):
                with self.assertRaises(ValueError):
                    search(database, **options)
            self.assertEqual(get_job(database, 19)["it_classification"], "uncertain")
            self.assertIsNone(get_job(database, 21)["german_eligibility_evidence"])

    def test_index_updates_closures_and_rollback(self):
        with closing(connect(":memory:")) as database:
            with database:
                source_id, records = seed(database)
            original = get_job(database, 2)
            with self.assertRaises(RuntimeError), database:
                database.execute("UPDATE jobs SET title = 'Rust Developer' WHERE id = 2")
                raise RuntimeError("rollback")
            self.assertEqual(search(database, "Go")[0]["id"], 2)
            database.execute("UPDATE jobs SET title = 'Rust Developer' WHERE id = 2")
            self.assertEqual(search(database, "Go"), [])
            self.assertEqual(search(database, "Rust")[0]["id"], 2)
            database.execute("UPDATE jobs SET closed_at = '2026-09-10' WHERE id = 2")
            self.assertEqual(search(database, "Rust"), [])
            self.assertIsNotNone(get_job(database, 2)["closed_at"])
            save_jobs(database, source_id, [records[1]], "2026-09-11")
            self.assertEqual(search(database, "Go")[0]["id"], original["id"])
            database.execute("DELETE FROM jobs WHERE id = 2")
            self.assertEqual(search(database, "Go"), [])

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
                self.assertEqual((result[0] if isinstance(result, list) else result)["id"], 2)
                self.assertEqual(err.getvalue(), "")
            for command in (["show", "999", "--json"], ["show", "0"], ["search", "--limit", "101"], ["nonsense"]):
                out, err = io.StringIO(), io.StringIO()
                with patch("sys.argv", ["jobsh", "--db", str(path), *command]), redirect_stdout(out), redirect_stderr(err):
                    with self.assertRaises(SystemExit) as error:
                        main()
                self.assertNotEqual(error.exception.code, 0)
                self.assertEqual(out.getvalue(), "")
                self.assertTrue(err.getvalue())

    def test_existing_jobs_are_classified_and_indexed_on_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            with closing(sqlite3.connect(path)) as database, database:
                schema = MIGRATION.read_text().replace("    source_category TEXT,\n", "").replace("    classification_rule TEXT,\n", "")
                database.executescript(schema)
                register_source(database, "personio", "example", URL, "manual")
                database.execute(
                    "INSERT INTO jobs (source_id, external_id, title, locations, work_mode, "
                    "original_url, first_seen_at, last_seen_at, content_hash, raw_record) "
                    "VALUES (1, '1', 'Go Developer', '[]', 'remote', ?, 'first', 'last', 'hash', '<position/>')",
                    (URL,),
                )
            for _ in range(2):
                with closing(connect(path)) as database:
                    job, = search(database, "Go")
                    self.assertEqual(job["classification_rule"], "title:technical_role")
                    self.assertEqual((job["id"], job["first_seen_at"], job["content_hash"]), (1, "first", "hash"))
