import io
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

from dev_monitor import providers
from dev_monitor.providers import base
from dev_monitor.providers.base import ProviderError
from tests.helpers import git, make_repo

SLUG = base.SLUG


def http_error(code, headers=None):
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError("https://api.example.com/x", code, "error", message, io.BytesIO(b"{}"))


class NormalizeHostTests(unittest.TestCase):
    def test_normalize_host(self):
        self.assertEqual(base.normalize_host("gitlab", None), "gitlab.com")
        self.assertEqual(base.normalize_host("gitlab", ""), "gitlab.com")
        self.assertEqual(base.normalize_host("gitlab", "Git.Example.com"), "git.example.com")
        self.assertEqual(base.normalize_host("gitlab", "https://git.example.com/"), "git.example.com")
        self.assertEqual(base.normalize_host("gitlab", "git.example.com:8443"), "git.example.com:8443")
        self.assertEqual(base.normalize_host("local", None), "")
        for bad in ("http://git.example.com", "https://git.example.com/path", "https://u:p@git.example.com",
                    "https://git.example.com/?q=1"):
            with self.assertRaises(ProviderError, msg=bad):
                base.normalize_host("gitlab", bad)


class ParseSourceTests(unittest.TestCase):
    def test_parse_hosted_source(self):
        self.assertEqual(base.parse_hosted_source("octo-org/widgets", "github.com", SLUG), ("slug", "octo-org/widgets"))
        self.assertEqual(base.parse_hosted_source("https://github.com/octo-org/widgets.git/", "github.com", SLUG),
                         ("slug", "octo-org/widgets"))
        self.assertEqual(base.parse_hosted_source("git@github.com:octo-org/widgets.git", "github.com", SLUG),
                         ("slug", "octo-org/widgets"))
        with self.assertRaisesRegex(ProviderError, "not on github.com"):
            base.parse_hosted_source("https://gitlab.com/octo-org/widgets", "github.com", SLUG)
        with tempfile.TemporaryDirectory() as directory:
            kind, value = base.parse_hosted_source(directory, "github.com", SLUG)
            self.assertEqual((kind, Path(value)), ("path", Path(directory).resolve()))
        self.assertEqual(base.parse_hosted_source("", "github.com", SLUG), ("path", ""))
        with self.assertRaises(ProviderError):
            base.parse_hosted_source("not a repo", "github.com", SLUG)


class OriginRemoteTests(unittest.TestCase):
    def test_origin_remote_forms(self):
        forms = {"https://github.com/octo-org/widgets.git": ("github.com", "octo-org/widgets"),
                 "ssh://git@git.example.com:2222/group/sub/proj.git": ("git.example.com", "group/sub/proj"),
                 "git@bitbucket.org:ws/repo.git": ("bitbucket.org", "ws/repo")}
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / "r")
            self.assertIsNone(base.origin_remote(repo))
            for url, expected in forms.items():
                git(repo, "remote", "remove", "origin") if base.origin_remote(repo) else None
                git(repo, "remote", "add", "origin", url)
                self.assertEqual(base.origin_remote(repo), expected, url)


class HttpTests(unittest.TestCase):
    def check(self, error, status, prefix):
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ProviderError) as context:
                base.http_json("https://api.example.com/x", headers={"Authorization": "Bearer sekret"}, provider="gitlab")
        self.assertEqual(context.exception.status, status)
        self.assertTrue(str(context.exception).startswith(prefix), str(context.exception))
        self.assertNotIn("sekret", str(context.exception))

    def test_http_errors(self):
        self.check(http_error(401), 401, "GitLab rejected the token")
        self.check(http_error(404), 404, "GitLab could not find")
        self.check(http_error(429, {"Retry-After": "30"}), 429, "GitLab rate limit reached. Try again after ")
        self.check(http_error(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1893456000"}), 429,
                   "GitLab rate limit reached")
        self.check(urllib.error.URLError("nope"), 502, "Could not reach api.example.com")

    def test_http_json_returns_body_and_lowercase_headers(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"ok": true}'
        response.headers.items.return_value = [("X-Next-Page", "2")]
        with mock.patch("urllib.request.urlopen", return_value=response) as opener:
            body, headers = base.http_json("https://api.example.com/x", provider="github")
        self.assertEqual(body, {"ok": True})
        self.assertEqual(headers, {"x-next-page": "2"})
        self.assertTrue(opener.call_args.args[0].get_header("User-agent").startswith("dev-monitor/"))

    def test_http_json_post_body(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"{}"
        response.headers.items.return_value = []
        with mock.patch("urllib.request.urlopen", return_value=response) as opener:
            base.http_json("https://api.example.com/graphql", provider="github", data=b'{"q": 1}')
        request = opener.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, b'{"q": 1}')
        self.assertEqual(request.get_header("Content-type"), "application/json")

    def test_registry_unknown(self):
        with self.assertRaises(ProviderError):
            providers.get("svn")


if __name__ == "__main__":
    unittest.main()
