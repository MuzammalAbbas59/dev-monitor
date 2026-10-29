import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dev_monitor.auth import Credential
from dev_monitor.providers import base, github
from dev_monitor.providers.base import ProviderError
from tests.helpers import commit, git, make_repo

FIXTURES = Path(__file__).parent / "fixtures"
TOKEN = Credential("tok")


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeApi:
    def __init__(self, routes=None, graphql=None):
        self.routes = routes or {}
        self.graphql = list(graphql or [])
        self.calls = []

    def __call__(self, url, *, headers=None, provider, timeout=30, data=None):
        self.calls.append({"url": url, "headers": headers, "data": json.loads(data) if data else None})
        if data is not None:
            return self.graphql.pop(0), {}
        for suffix, body in self.routes.items():
            if url.endswith(suffix):
                if isinstance(body, Exception):
                    raise body
                return body, {}
        raise AssertionError(f"unexpected url {url}")


class GitHubTests(unittest.TestCase):
    def test_inspect_slug(self):
        api = FakeApi({"/repos/octo-org/widgets": {"full_name": "octo-org/widgets", "default_branch": "main"},
                       "/repos/octo-org/widgets/branches?per_page=100": [{"name": "main"}, {"name": "dev"}]})
        with mock.patch.object(base, "http_json", api):
            result = github.inspect("octo-org/widgets", "github.com", TOKEN)
        self.assertEqual(result["repository"], "octo-org/widgets")
        self.assertEqual(result["default_branch"], "main")
        self.assertEqual(result["branches"], ["main", "dev"])
        self.assertIsNone(result["checkout_path"])
        self.assertEqual(api.calls[0]["url"], "https://api.github.com/repos/octo-org/widgets")
        self.assertEqual(api.calls[0]["headers"], {"Authorization": "Bearer tok"})

    def test_enterprise_base_url(self):
        api = FakeApi({"/repos/octo-org/widgets": {"full_name": "octo-org/widgets", "default_branch": "main"},
                       "branches?per_page=100": []})
        with mock.patch.object(base, "http_json", api):
            github.inspect("octo-org/widgets", "ghe.example.com", TOKEN)
        self.assertEqual(api.calls[0]["url"], "https://ghe.example.com/api/v3/repos/octo-org/widgets")

    def test_inspect_path_resolves_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_repo(Path(directory) / "w")
            commit(repo, "init")
            git(repo, "switch", "-q", "-c", "feature")
            git(repo, "remote", "add", "origin", "git@github.com:octo-org/widgets.git")
            api = FakeApi({"/repos/octo-org/widgets": {"full_name": "octo-org/widgets", "default_branch": "main"},
                           "branches?per_page=100": [{"name": "main"}]})
            with mock.patch.object(base, "http_json", api):
                result = github.inspect(str(repo), "github.com", TOKEN)
            self.assertEqual(result["current_branch"], "feature")
            self.assertEqual(result["repository"], "octo-org/widgets")
            self.assertEqual(Path(result["checkout_path"]), repo.resolve())
            git(repo, "remote", "set-url", "origin", "https://gitlab.com/octo-org/widgets.git")
            with mock.patch.object(base, "http_json", api), self.assertRaisesRegex(ProviderError, "gitlab.com"):
                github.inspect(str(repo), "github.com", TOKEN)

    def test_collect_paginates_and_maps(self):
        api = FakeApi(graphql=[fixture("github_page1.json"), fixture("github_page2.json")])
        with mock.patch.object(base, "http_json", api):
            records = github.collect("octo-org/widgets", "main", "github.com", TOKEN, {})
        self.assertEqual([r["number"] for r in records], [3, 2, 1])
        self.assertEqual(records[0], {"number": 3, "title": "Third", "description": "c",
                                      "url": "https://github.com/octo-org/widgets/pull/3", "author": "alice",
                                      "merged_by": "bob", "merged_at": "2026-01-03T10:00:00Z",
                                      "provider": "github", "host": "github.com", "sha": None})
        self.assertEqual(records[2]["description"], "")
        self.assertEqual(api.calls[0]["url"], "https://api.github.com/graphql")
        self.assertEqual(api.calls[0]["data"]["variables"],
                         {"owner": "octo-org", "name": "widgets", "branch": "main", "cursor": None})
        self.assertEqual(api.calls[1]["data"]["variables"]["cursor"], "CUR1")

    def test_null_author_and_merger(self):
        api = FakeApi(graphql=[fixture("github_page1.json"), fixture("github_page2.json")])
        with mock.patch.object(base, "http_json", api):
            records = github.collect("octo-org/widgets", "main", "github.com", TOKEN, {})
        self.assertIsNone(records[2]["author"])
        self.assertIsNone(records[2]["merged_by"])

    def test_requires_token(self):
        with self.assertRaisesRegex(ProviderError, "GitHub needs a token"):
            github.collect("octo-org/widgets", "main", "github.com", None, {})

    def test_branch_exists(self):
        api = FakeApi({"/branches/feat%2Fx": {"name": "feat/x"},
                       "/branches/gone": ProviderError("missing", 404)})
        with mock.patch.object(base, "http_json", api):
            self.assertTrue(github.branch_exists("octo-org/widgets", "feat/x", "github.com", TOKEN))
            self.assertFalse(github.branch_exists("octo-org/widgets", "gone", "github.com", TOKEN))


if __name__ == "__main__":
    unittest.main()
