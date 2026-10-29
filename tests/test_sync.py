import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from dev_monitor import sync
from dev_monitor.providers.base import ProviderError
from tests.helpers import record


def fake_provider(records=None, error=None):
    module = types.SimpleNamespace(NAME="github", calls=[])

    def collect(repository, branch, host, credential, previous):
        module.calls.append(previous)
        if error:
            raise error
        return [dict(item) for item in records]
    module.collect = collect
    return module


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name) / "out"

    def tearDown(self):
        self.temporary.cleanup()

    def run_sync(self, provider, branch="main"):
        with mock.patch("dev_monitor.providers.get", return_value=provider):
            return sync.sync_to_directory("github", "github.com", "octo-org/widgets", branch, "UTC", None, self.directory)

    def test_first_seen_title_kept(self):
        self.run_sync(fake_provider([record(title="Original", description="first")]))
        snapshot, _ = self.run_sync(fake_provider([record(title="Edited", description="second")]))
        self.assertEqual((snapshot["records"][0]["title"], snapshot["records"][0]["description"]), ("Original", "first"))

    def test_previous_ignored_for_other_branch(self):
        self.run_sync(fake_provider([record(title="Original")]))
        provider = fake_provider([record(title="Edited")])
        snapshot, _ = self.run_sync(provider, branch="release")
        self.assertEqual(provider.calls[0], {})
        self.assertEqual(snapshot["records"][0]["title"], "Edited")

    def test_previous_passed_keyed(self):
        self.run_sync(fake_provider([record(number=4)]))
        provider = fake_provider([record(number=4)])
        self.run_sync(provider)
        self.assertEqual(list(provider.calls[0]), ["#4"])

    def test_synced_at_stable_when_unchanged(self):
        first, _ = self.run_sync(fake_provider([record()]))
        second, changed = self.run_sync(fake_provider([record()]))
        self.assertEqual(first["synced_at"], second["synced_at"])
        self.assertEqual(changed, [])
        third, _ = self.run_sync(fake_provider([record(), record(number=2)]))
        self.assertNotEqual(third["records"], first["records"])
        self.assertEqual(set(third), {"provider", "host", "repository", "branch", "timezone", "synced_at", "records"})

    def test_failed_sync_keeps_snapshot(self):
        self.run_sync(fake_provider([record()]))
        before = (self.directory / "records.json").read_bytes()
        with self.assertRaises(ProviderError):
            self.run_sync(fake_provider(error=ProviderError("GitHub rejected the token.", 401)))
        self.assertEqual((self.directory / "records.json").read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.directory.parent.iterdir()), ["out"])
        self.assertEqual(sorted(path.name for path in self.directory.iterdir()),
                         ["REPORT.md", "index.html", "merges.csv", "records.json"])

    def test_validate_branch_rejects_dash_and_bad_refs(self):
        self.assertEqual(sync.validate_branch(" release/1.0 "), "release/1.0")
        self.assertEqual(sync.validate_branch("origin/main"), "origin/main")
        for bad in ("", "-x", "a..b", "has space", "x" * 256, None):
            with self.assertRaises(ProviderError, msg=repr(bad)):
                sync.validate_branch(bad)

    def test_validate_timezone(self):
        self.assertEqual(sync.validate_timezone("Asia/Karachi"), "Asia/Karachi")
        for bad in ("CST6", "Mars/Base", "", "../etc", None):
            with self.assertRaisesRegex(ProviderError, "IANA", msg=repr(bad)):
                sync.validate_timezone(bad)


if __name__ == "__main__":
    unittest.main()
