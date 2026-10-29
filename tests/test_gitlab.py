import json
import unittest
from pathlib import Path
from unittest import mock

from dev_monitor.auth import Credential
from dev_monitor.providers import base, gitlab

FIXTURES = Path(__file__).parent / "fixtures"


class FakeApi:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url, *, headers=None, provider, timeout=30, data=None):
        self.calls.append({"url": url, "headers": headers})
        for key, value in self.responses.items():
            if key in url:
                return value
        raise AssertionError(url)


def pages():
    return FakeApi({"page=1&": (json.loads((FIXTURES / "gitlab_mrs_p1.json").read_text()), {"x-next-page": "2"}),
                    "page=2&": (json.loads((FIXTURES / "gitlab_mrs_p2.json").read_text()), {"x-next-page": ""})})


class GitLabTests(unittest.TestCase):
    def test_inspect_nested_group(self):
        api = FakeApi({"/repository/branches": ([{"name": "main"}], {}),
                       "/projects/group%2Fsub%2Fproj": ({"path_with_namespace": "group/sub/proj",
                                                         "default_branch": "main"}, {})})
        with mock.patch.object(base, "http_json", api):
            result = gitlab.inspect("https://gitlab.com/group/sub/proj", "gitlab.com", Credential("tok"))
        self.assertEqual((result["repository"], result["default_branch"], result["branches"]),
                         ("group/sub/proj", "main", ["main"]))
        self.assertEqual(api.calls[0]["url"], "https://gitlab.com/api/v4/projects/group%2Fsub%2Fproj")
        self.assertEqual(api.calls[0]["headers"], {"PRIVATE-TOKEN": "tok"})
        self.assertIn("/projects/group%2Fsub%2Fproj/repository/branches?per_page=100", api.calls[1]["url"])

    def test_collect_paginates_via_x_next_page(self):
        api = pages()
        with mock.patch.object(base, "http_json", api):
            records = gitlab.collect("group/sub/proj", "release/1.0", "gitlab.com", None, {})
        self.assertEqual(len(api.calls), 2)
        url = api.calls[0]["url"]
        for part in ("state=merged", "target_branch=release%2F1.0", "per_page=100", "page=1&"):
            self.assertIn(part, url)
        self.assertEqual(api.calls[0]["headers"], {})
        self.assertEqual([r["number"] for r in records], [9, 8, 7])

    def test_mapping(self):
        with mock.patch.object(base, "http_json", pages()):
            nine, eight, seven = gitlab.collect("group/sub/proj", "main", "gitlab.com", None, {})
        self.assertEqual(nine, {"number": 9, "title": "Nine", "description": "d9",
                                "url": "https://gitlab.com/group/sub/proj/-/merge_requests/9", "author": "alice",
                                "merged_by": "bob", "merged_at": "2026-01-02T03:04:05Z", "provider": "gitlab",
                                "host": "gitlab.com", "sha": None})
        self.assertEqual((eight["merged_by"], eight["description"], eight["merged_at"]),
                         ("alice", "", "2026-01-01T05:00:00Z"))
        self.assertIsNone(seven["author"])
        self.assertIsNone(seven["merged_by"])

    def test_skips_merged_without_timestamp(self):
        with mock.patch.object(base, "http_json", pages()):
            records = gitlab.collect("group/sub/proj", "main", "gitlab.com", None, {})
        self.assertNotIn(6, [r["number"] for r in records])

    def test_self_hosted_base_url(self):
        api = pages()
        with mock.patch.object(base, "http_json", api):
            gitlab.collect("group/sub/proj", "main", "git.example.com", Credential("tok"), {})
        self.assertTrue(api.calls[0]["url"].startswith("https://git.example.com/api/v4/projects/group%2Fsub%2Fproj/merge_requests?"))


if __name__ == "__main__":
    unittest.main()
