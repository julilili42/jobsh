import json
import unittest
from pathlib import Path

from jobsh.discovery import candidate_hosts
from jobsh.personio_feed import validated_positions, normalize_feed

FIXTURES = Path(__file__).parents[1] / "testdata"


class PersonioTest(unittest.TestCase):
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
                        "original_url": "https://example.jobs.personio.de/job/1?display=de",
                        "german_eligibility_evidence": office or None,
                        "published_at": "2026-09-01",
                    },
                )

    def test_common_crawl_hosts_are_unique(self) -> None:
        records = [
            json.loads(line)
            for line in (FIXTURES / "common-crawl.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            candidate_hosts(records, "jobs.personio.de"),
            ["alpha.jobs.personio.de", "beta.jobs.personio.de"],
        )

    def test_candidate_hosts_supports_other_domains(self) -> None:
        records = [{"url": url} for url in (
            "https://beta.jobs.example/xml",
            "https://ALPHA.jobs.example/",
            "https://alpha.jobs.example/xml",
            "https://jobs.example/",
            "https://nested.alpha.jobs.example/",
            "https://alpha.jobs.example.evil/",
            "https://notjobs.example/",
            "https://alpha.jobs.personio.de/",
            "",
        )]
        self.assertEqual(
            candidate_hosts(records, "JOBS.EXAMPLE"),
            ["alpha.jobs.example", "beta.jobs.example"],
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
