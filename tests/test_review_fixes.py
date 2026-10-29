import csv
import io
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from dev_monitor import auth, reports, server, sync
from dev_monitor.auth import Credential
from dev_monitor.providers import base, bitbucket
from dev_monitor.providers.base import ProviderError
from tests.helpers import record, snapshot


class _Recorder(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.server.redirect_to:
            self.send_response(302)
            self.send_header("Location", self.server.redirect_to)
            self.end_headers()
            return
        _Recorder.seen.append(dict(self.headers))
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve(redirect_to=None):
    httpd = HTTPServer(("127.0.0.1", 0), _Recorder)
    httpd.redirect_to = redirect_to
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


class RedirectTests(unittest.TestCase):
    def test_token_never_follows_redirect(self):
        _Recorder.seen = []
        target = _serve()
        source = _serve(f"http://localhost:{target.server_port}/steal")
        try:
            with self.assertRaisesRegex(ProviderError, "redirected"):
                base.http_json(f"http://127.0.0.1:{source.server_port}/api", headers={"PRIVATE-TOKEN": "SECRET"},
                               provider="gitlab")
            self.assertEqual(_Recorder.seen, [])
        finally:
            for httpd in (source, target):
                httpd.shutdown()
                httpd.server_close()


class BranchValidationTests(unittest.TestCase):
    def test_hosted_branch_validation_needs_no_git(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(sync.validate_branch("release/1.0", "github"), "release/1.0")
            for bad in ("a..b", "has space", "x.lock", "a@{b", "/x", "x/", "a~b", "-x", "a\x01b"):
                with self.assertRaises(ProviderError, msg=bad):
                    sync.validate_branch(bad, "gitlab")

    def test_local_branch_validation_still_uses_git(self):
        self.assertEqual(sync.validate_branch("origin/main", "local"), "origin/main")


class CsvInjectionTests(unittest.TestCase):
    def test_formula_cells_are_neutralized(self):
        data = snapshot([record(title='=HYPERLINK("http://x","a")', author="+alice", merged_by="@bob",
                                description="-1+2")])
        row = list(csv.reader(io.StringIO(reports.csv_report(data))))[1]
        self.assertEqual(row[1], '\'=HYPERLINK("http://x","a")')
        self.assertEqual((row[2], row[4], row[5]), ("'-1+2", "'+alice", "'@bob"))


class WindowsPortTests(unittest.TestCase):
    def test_server_does_not_share_ports_on_windows(self):
        self.assertEqual(server.MonitorServer.allow_reuse_address, sys.platform != "win32")
        app = server.MonitorApp(mock.Mock(tool_id="x"), None, env={}, gh_token=lambda: None)
        bound, _ = server.bind(app, 0)
        try:
            self.assertIsInstance(bound, server.MonitorServer)
        finally:
            bound.server_close()


class RejectedTokenTests(unittest.TestCase):
    def test_env_token_rejection_names_variable(self):
        error = ProviderError("GitHub rejected the token. Create a new one and save it again.", 401)
        explained = auth.explain_rejection(error, Credential("t", source="env:GITHUB_TOKEN"), "github")
        self.assertIn("GITHUB_TOKEN", str(explained))
        self.assertEqual(explained.status, 401)
        gh = auth.explain_rejection(error, Credential("t", source="gh"), "github")
        self.assertIn("gh auth login", str(gh))
        self.assertIs(auth.explain_rejection(error, Credential("t"), "github"), error)
        other = ProviderError("not found", 404)
        self.assertIs(auth.explain_rejection(other, Credential("t", source="env:GITHUB_TOKEN"), "github"), other)

    def test_resolve_marks_source(self):
        store = mock.Mock(saved_credential=mock.Mock(return_value=None))
        self.assertEqual(auth.resolve_credential("github", "github.com", store, {"GITHUB_TOKEN": "e"}, lambda: None).source,
                         "env:GITHUB_TOKEN")
        self.assertEqual(auth.resolve_credential("github", "github.com", store, {}, lambda: "g").source, "gh")

    def test_gh_cache_refreshes_after_save(self):
        calls = iter(["old", "new"])
        store = mock.Mock(saved_credential=mock.Mock(return_value=None), credential_flags=mock.Mock(return_value={}))
        app = server.MonitorApp(store, None, env={}, gh_token=lambda: next(calls))
        self.assertEqual(app.credential("github", "github.com").token, "old")
        app.save_credentials({"provider": "gitlab", "token": "abc"})
        self.assertEqual(app.credential("github", "github.com").token, "new")


class BitbucketFieldsTests(unittest.TestCase):
    def test_fields_only_extend_default_response(self):
        self.assertTrue(all(part.startswith("+") for part in bitbucket.FIELDS.split(",")), bitbucket.FIELDS)


if __name__ == "__main__":
    unittest.main()
