import json
import unittest
from pathlib import Path
from unittest.mock import patch

from jobsh.discovery import discover
from jobsh.adapters.personio import validated_positions, normalize_feed, source

FIXTURES = Path(__file__).parents[1] / "testdata"


class PersonioTest(unittest.TestCase):
    def test_source_supports_both_personio_domains(self) -> None:
        for domain in ("jobs.personio.de", "jobs.personio.com"):
            self.assertEqual(
                source(f"https://example.{domain}/job/1"),
                ("example", f"https://example.{domain}/xml?language=de"),
            )

    def test_normalization_preserves_fields_and_ignores_xml_formatting(self) -> None:
        for office, description, mode in (
            ("Berlin", "Remote und Hybrid", "hybrid"),
            ("Berlin", "Remote", "remote"),
            ("", "Homeoffice", "remote"),
            ("Berlin", "", "onsite"),
            ("", "", "unknown"),
        ):
            with self.subTest(mode=mode, description=description):
                xml = (
                    '<workzag-jobs xmlns="urn:personio"><position>'
                    '<id> 1 </id><name> Developer </name>'
                    f'<office> {office} </office><office> </office>'
                    '<employmentType> permanent </employmentType>'
                    '<createdAt> 2026-09-01 </createdAt>'
                    '<jobDescriptions><jobDescription><name> Arbeit </name>'
                    f'<value> {description} </value></jobDescription></jobDescriptions>'
                    '</position></workzag-jobs>'
                ).encode()
                url = "https://example.jobs.personio.de/xml?language=de"
                record, = normalize_feed(xml, url)
                reformatted, = normalize_feed(xml.replace(b"><", b">\n<"), url)
                self.assertEqual(record["content_hash"], reformatted["content_hash"])
                self.assertNotEqual(record["raw_record"], reformatted["raw_record"])
                self.assertEqual(
                    {key: value for key, value in record.items()
                     if key not in ("content_hash", "raw_record")},
                    {
                        "external_id": "1", "title": "Developer",
                        "description": "Arbeit" + ("\n" + description if description else ""),
                        "locations": json.dumps([office] if office else []),
                        "location_text": office or None, "work_mode": mode,
                        "employment_type": "permanent",
                        "source_category": None,
                        "original_url": "https://example.jobs.personio.de/job/1?display=de",
                        "published_at": "2026-09-01",
                    },
                )

    @patch("jobsh.adapters.personio.fetch", return_value=b"<workzag-jobs />")
    @patch("jobsh.discovery.records")
    def test_common_crawl_hosts_are_unique(self, records, fetch) -> None:
        records.return_value = [
            json.loads(line)
            for line in (FIXTURES / "common-crawl.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            [account for account, _, _ in discover("personio", 0, 1, 3)],
            ["alpha", "beta"],
        )

    @patch("jobsh.adapters.personio.fetch", return_value=b"<workzag-jobs />")
    @patch("jobsh.discovery.records")
    def test_discovery_filters_hosts_and_known_accounts(self, records, fetch) -> None:
        records.return_value = [{"url": url} for url in (
            "https://beta.jobs.personio.de/xml",
            "https://ALPHA.jobs.personio.de/",
            "https://alpha.jobs.personio.de/xml",
            "https://jobs.personio.de/",
            "https://nested.alpha.jobs.personio.de/",
            "https://alpha.jobs.personio.de.evil/",
            "https://notjobs.personio.de/",
            "https://alpha.jobs.example/",
            "",
        )]
        self.assertEqual(
            [account for account, _, _ in discover("personio", 0, 1, 3)],
            ["alpha", "beta"],
        )
        self.assertEqual(
            [account for account, _, _ in discover("personio", 0, 1, 3, {"alpha"})],
            ["beta"],
        )

    def test_feed_requires_personio_xml_with_complete_positions(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid Personio XML"):
            validated_positions(b"<workzag-jobs>")
        self.assertEqual(len(validated_positions((FIXTURES / "personio.xml").read_bytes())), 1)
        self.assertEqual(
            len(validated_positions(
                b'<workzag-jobs xmlns="urn:personio"><position>'
                b"<id> 1 </id><name> Developer </name>"
                b"</position></workzag-jobs>"
            )),
            1,
        )
        with self.assertRaises(ValueError):
            validated_positions(b"<html></html>")
        with self.assertRaises(ValueError):
            validated_positions(b"<workzag-jobs><position><id>1</id></position></workzag-jobs>")
        with self.assertRaises(ValueError):
            validated_positions(
                b"<workzag-jobs><position><id> </id><name>Developer</name>"
                b"</position></workzag-jobs>"
            )
        with self.assertRaisesRegex(ValueError, "duplicate position id"):
            validated_positions(
                b"<workzag-jobs><position><id>1</id><name>A</name></position>"
                b"<position><id>1</id><name>B</name></position></workzag-jobs>"
            )
        with self.assertRaisesRegex(ValueError, "DOCTYPE is not allowed"):
            validated_positions(b"<!DOCTYPE jobs><workzag-jobs />")


if __name__ == "__main__":
    unittest.main()
