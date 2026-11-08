import http.client
import io
import json
import os
import ssl
import sys
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from dev_monitor import reports, server, storage, sync
from dev_monitor.providers import base, bitbucket, local
from dev_monitor.providers.base import ProviderError
from tests.helpers import record, snapshot
from tests.test_sync import fake_provider


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


class _BrokenResponse:
    def __init__(self, error):
        self.error = error
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        raise self.error


class NetworkMessageTests(unittest.TestCase):
    def call(self, **patch):
        with mock.patch.object(base._OPENER, "open", **patch):
            with self.assertRaises(ProviderError) as caught:
                base.http_json("https://gitlab.example.com/api/v4/projects", provider="gitlab")
        return caught.exception

    def test_connection_dropped_mid_response(self):
        for error in (ConnectionResetError(), http.client.IncompleteRead(b""), http.client.RemoteDisconnected()):
            failure = self.call(return_value=_BrokenResponse(error))
            self.assertIn("connection to gitlab.example.com dropped", str(failure))
            self.assertEqual(failure.status, 502)

    def test_untrusted_certificate(self):
        error = urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))
        self.assertIn("certificate", str(self.call(side_effect=error)))


class SyncExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name) / "out"

    def tearDown(self):
        self.temporary.cleanup()

    def run_sync(self):
        with mock.patch("dev_monitor.providers.get", return_value=fake_provider([record()])):
            return sync.sync_to_directory("github", "github.com", "octo-org/widgets", "main", "UTC", None,
                                          self.directory)

    def locked(self, failures):
        """os.replace that fails for the first `failures` writes into the output folder (not the staging folder)."""
        real, attempts = os.replace, []

        def replace(source, target):
            if Path(target).parent == self.directory:
                attempts.append(target)
                if len(attempts) <= failures:
                    raise PermissionError(13, "in use")
            real(source, target)
        return replace

    def test_locked_export_names_the_file(self):
        with mock.patch.object(sync.time, "sleep"), mock.patch.object(sync.os, "replace", self.locked(99)):
            with self.assertRaisesRegex(ProviderError, "index.html is open in another program") as caught:
                self.run_sync()
        self.assertEqual(caught.exception.status, 423)

    def test_locked_export_retries_before_failing(self):
        with mock.patch.object(sync.time, "sleep"), mock.patch.object(sync.os, "replace", self.locked(1)):
            self.run_sync()
        self.assertTrue((self.directory / "index.html").exists())

    @unittest.skipIf(sys.platform == "win32", "POSIX permissions")
    def test_exports_are_shareable(self):
        self.run_sync()
        for name in sync.EXPORTS:
            self.assertEqual((self.directory / name).stat().st_mode & 0o777, 0o644, name)


class CsvEncodingTests(unittest.TestCase):
    def test_csv_starts_with_utf8_bom_for_excel(self):
        text = reports.csv_report(snapshot([record(author="José")]))
        self.assertTrue(text.startswith("\ufeffPR number,"))


class QuotedPathTests(unittest.TestCase):
    def test_quotes_around_pasted_path_are_removed(self):
        app = server.MonitorApp(mock.Mock(tool_id="x"), None, env={}, gh_token=lambda: None)
        for pasted in ('"C:\\Users\\me\\repo"', "'/home/me/repo'", '  "/home/me/my repo"  '):
            _, _, _, source = app._target({"provider": "local", "source": pasted})
            self.assertFalse(source.startswith(("'", '"')) or source.endswith(("'", '"')), source)


if __name__ == "__main__":
    unittest.main()
