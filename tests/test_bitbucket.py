import base64
import json
import unittest
from pathlib import Path
from unittest import mock

from dev_monitor.auth import Credential
from dev_monitor.providers import base, bitbucket
from dev_monitor.providers.base import ProviderError

FIXTURES = Path(__file__).parent / "fixtures"


class FakeApi:
    def __init__(self):
        self.calls = []

    def __call__(self, url, *, headers=None, provider, timeout=30, data=None):
        self.calls.append({"url": url, "headers": headers})
        if url.endswith("page=2"):
            return json.loads((FIXTURES / "bitbucket_prs_p2.json").read_text()), {}
        if "/pullrequests?" in url:
            return json.loads((FIXTURES / "bitbucket_prs_p1.json").read_text()), {}
        if "/commit/abc7" in url:
            return {"date": "2026-01-07T10:15:00+00:00"}, {}
        if "/refs/branches" in url:
            return {"values": [{"name": "main"}, {"name": "dev"}]}, {}
        if url.endswith("/repositories/ws/repo"):
            return {"full_name": "ws/repo", "mainbranch": {"name": "main"}}, {}
        raise AssertionError(url)


class BitbucketTests(unittest.TestCase):
    def collect(self, previous=None, credential=None):
        api = FakeApi()
        with mock.patch.object(base, "http_json", api):
            records = bitbucket.collect("ws/repo", "main", "bitbucket.org", credential, previous or {})
        return records, api

    def test_inspect(self):
        api = FakeApi()
        with mock.patch.object(base, "http_json", api):
            result = bitbucket.inspect("https://bitbucket.org/ws/repo", "bitbucket.org", Credential("tok", "a@x.io"))
        self.assertEqual((result["repository"], result["default_branch"], result["branches"]),
                         ("ws/repo", "main", ["main", "dev"]))
        expected = "Basic " + base64.b64encode(b"a@x.io:tok").decode()
        self.assertEqual(api.calls[0]["headers"], {"Authorization": expected})
        self.assertIn("/repositories/ws/repo/refs/branches?pagelen=100", api.calls[1]["url"])

    def test_only_bitbucket_cloud(self):
        with self.assertRaisesRegex(ProviderError, "Only Bitbucket Cloud"):
            bitbucket.inspect("ws/repo", "bb.example.com", None)

    def test_collect_follows_next(self):
        records, api = self.collect()
        first = api.calls[0]["url"]
        self.assertTrue(first.startswith("https://api.bitbucket.org/2.0/repositories/ws/repo/pullrequests?"))
        for part in ("state=MERGED", "pagelen=50", "q=destination.branch.name%3D%22main%22"):
            self.assertIn(part, first)
        self.assertEqual([r["number"] for r in records], [7, 6, 5])
        self.assertEqual(api.calls[0]["headers"], {})

    def test_mapping(self):
        records, _ = self.collect()
        seven, six, five = records
        self.assertEqual(seven, {"number": 7, "title": "Seven", "description": "d7",
                                 "url": "https://bitbucket.org/ws/repo/pull-requests/7", "author": "alice",
                                 "merged_by": "Bob B", "merged_at": "2026-01-07T10:15:00Z", "provider": "bitbucket",
                                 "host": "bitbucket.org", "sha": None})
        self.assertEqual((six["author"], six["merged_by"]), (None, None))
        self.assertEqual((five["author"], five["merged_by"], five["description"]), ("Carol", "bob", ""))

    def test_merged_at_order(self):
        seven, six, five = self.collect()[0]
        self.assertEqual(six["merged_at"], "2026-01-06T09:30:00Z")
        self.assertEqual(seven["merged_at"], "2026-01-07T10:15:00Z")
        self.assertEqual(five["merged_at"], "2026-01-05T08:00:00Z")

    def test_merged_at_reuses_previous(self):
        previous = {"#7": {"number": 7, "merged_at": "2026-01-07T10:00:00Z"}}
        records, api = self.collect(previous)
        self.assertFalse(any("/commit/" in call["url"] for call in api.calls))
        self.assertEqual(records[0]["merged_at"], "2026-01-07T10:00:00Z")

    def test_next_link_must_stay_on_api_host(self):
        api = mock.Mock(return_value=({"values": [], "next": "https://evil.example.com/steal"}, {}))
        with mock.patch.object(base, "http_json", api), self.assertRaises(ProviderError):
            bitbucket.collect("ws/repo", "main", "bitbucket.org", Credential("tok", "a@x.io"), {})
        self.assertEqual(api.call_count, 1)


if __name__ == "__main__":
    unittest.main()
