import io
import json
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from dev_monitor import reports, storage
from dev_monitor.providers import base, bitbucket, local
from dev_monitor.providers.base import ProviderError
from tests.helpers import record, snapshot


class CredentialWriteTests(unittest.TestCase):
    def test_failed_write_keeps_existing_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            store = storage.Store(root)
            store.save_credential("github", "github.com", "OLD")
            with mock.patch.object(storage.json, "dump", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    store.save_credential("gitlab", "gitlab.com", "NEW")
            self.assertEqual(store.saved_credential("github", "github.com").token, "OLD")
            self.assertEqual([p.name for p in Path(root).iterdir()], ["credentials.json"])


class MarkdownEscapeTests(unittest.TestCase):
    def test_html_in_titles_is_escaped(self):
        report = reports.markdown_report(snapshot([record(title="Drop <script>alert(1)</script> & <b>")]))
        self.assertNotIn("<script>", report)
        self.assertIn("&lt;script>", report)


class LocalSubjectTests(unittest.TestCase):
    def test_squash_subject_with_trailing_carriage_return(self):
        self.assertEqual(local.classify("Fix login (#42)\r", "", "p1"), (42, "Fix login"))


class BitbucketQueryTests(unittest.TestCase):
    def test_quote_in_branch_name_is_escaped(self):
        seen = []

        def api(url, **kwargs):
            seen.append(url)
            return {"values": []}, {}

        with mock.patch.object(base, "http_json", api):
            bitbucket.collect("ws/repo", 'release"x', "bitbucket.org", None, {})
        self.assertEqual(parse_qs(urlsplit(seen[0]).query)["q"], ['destination.branch.name="release\\"x"'])


class SecondaryRateLimitTests(unittest.TestCase):
    def test_403_with_retry_after_is_a_rate_limit(self):
        headers = Message()
        headers["Retry-After"] = "60"
        error = urllib.error.HTTPError("https://api.github.com/graphql", 403, "Forbidden", headers, io.BytesIO(b"{}"))
        with mock.patch.object(base._OPENER, "open", side_effect=error):
            with self.assertRaisesRegex(ProviderError, "rate limit") as caught:
                base.http_json("https://api.github.com/graphql", provider="github")
        self.assertEqual(caught.exception.status, 429)


if __name__ == "__main__":
    unittest.main()
