import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from dev_monitor import reports
from tests.helpers import record, snapshot


class ReportTests(unittest.TestCase):
    def test_csv_columns(self):
        data = snapshot([record(), record(number=2)], timezone="Asia/Karachi")
        rows = list(csv.reader(io.StringIO(reports.csv_report(data))))
        self.assertEqual(rows[0], ["PR number", "Title", "Description", "URL", "Author", "Merged by",
                                   "Merged at (UTC)", "Merged at (display timezone)", "Display timezone", "Provider"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][7], "2026-01-02T01:00:00+05:00")
        self.assertEqual(rows[1][9], "github")

    def test_unknown_labels(self):
        data = snapshot([record(author=None, merged_by=None)])
        text_csv = reports.csv_report(data)
        text_md = reports.markdown_report(data)
        self.assertIn(reports.UNKNOWN, text_csv)
        self.assertIn(f"| {reports.UNKNOWN} | 1 |", text_md)
        self.assertNotIn("None", text_csv)
        self.assertNotIn("None", text_md)

    def test_markdown_links_use_record_url_and_host(self):
        hosted = reports.markdown_report(snapshot([record()], provider="gitlab", host="git.example.com"))
        self.assertIn("[octo-org/widgets](https://git.example.com/octo-org/widgets)", hosted)
        local = reports.markdown_report(snapshot([record(number=12, url=None, provider="local", host=""),
                                                  record(number=None, sha="abcdef1234", provider="local", host="")],
                                                 provider="local", host="", repository="/src/widgets"))
        self.assertIn("Repository: /src/widgets", local)
        self.assertIn("| #12 |", local)
        self.assertIn("| abcdef1 |", local)
        self.assertNotIn("](None)", local)

    def test_html_embed_escapes(self):
        title = "</script><b>& 😀|x\ny"
        encoded = reports.embed_json(snapshot([record(title=title)]))
        for forbidden in ("<", ">", "&", " "):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(json.loads(encoded)["records"][0]["title"], title)
        markdown = reports.markdown_report(snapshot([record(title=title)]))
        row = next(line for line in markdown.splitlines() if "😀" in line)
        self.assertIn("\\|x y", row)

    def test_empty_snapshot_renders(self):
        with tempfile.TemporaryDirectory() as directory:
            changed = reports.write_exports(snapshot([]), Path(directory))
            self.assertEqual(sorted(changed), ["REPORT.md", "index.html", "merges.csv", "records.json"])
            self.assertEqual(len((Path(directory) / "merges.csv").read_text().splitlines()), 1)

    def test_write_exports_reports_only_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            data = snapshot([record()])
            reports.write_exports(data, Path(directory))
            self.assertEqual(reports.write_exports(data, Path(directory)), [])


if __name__ == "__main__":
    unittest.main()
