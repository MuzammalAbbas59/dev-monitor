import os
import tempfile
import unittest
from pathlib import Path

from dev_monitor.providers import local
from dev_monitor.providers.base import ProviderError
from tests.helpers import commit, git, make_repo


class ClassifyTests(unittest.TestCase):
    def test_classify_table(self):
        one, two = ["a"], ["a", "b"]
        self.assertEqual(local.classify("Merge pull request #5 from octo-org/feature", "Add widgets\n", two),
                         (5, "Add widgets"))
        self.assertEqual(local.classify("Merge pull request #5 from octo-org/feature", "", two),
                         (5, "Merge pull request #5 from octo-org/feature"))
        self.assertEqual(local.classify("Merged in feature/x (pull request #12)", "\nBetter caching\n\nApproved-by: Bob", two),
                         (12, "Better caching"))
        self.assertEqual(local.classify("Merge branch 'feat' into 'main'", "Speed up search\n\nSee merge request group/proj!31", two),
                         (31, "Speed up search"))
        self.assertEqual(local.classify("Merge branch 'feat' into 'main'", "See merge request group/proj!31", two),
                         (31, "Merge branch 'feat' into 'main'"))
        self.assertEqual(local.classify("Fix login (#42)", "", one), (42, "Fix login"))
        self.assertEqual(local.classify("Merge branch 'x'", "", two), (None, "Merge branch 'x'"))
        self.assertIsNone(local.classify("Direct push", "", one))


class LocalRepoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def build(self, name="repo"):
        repo = make_repo(self.root / name)
        commit(repo, "Direct push", when="2026-01-01T09:00:00+00:00")
        git(repo, "switch", "-q", "-c", "feature")
        commit(repo, "Widget work", when="2026-01-01T10:00:00+00:00", author="bob", name="w.txt")
        git(repo, "switch", "-q", "main")
        git(repo, "merge", "-q", "--no-ff", "feature", "-m", "Merge pull request #5 from octo-org/feature\n\nAdd widgets",
            env={"GIT_COMMITTER_DATE": "2026-01-02T10:00:00+00:00", "GIT_AUTHOR_DATE": "2026-01-02T10:00:00+00:00"})
        commit(repo, "Tidy (#6)", when="2026-01-03T10:00:00+05:00", author="carol")
        return repo

    def test_collect_real_repo(self):
        repo = self.build()
        records = local.collect(str(repo.resolve()), "main", "", None, {})
        self.assertEqual([r["number"] for r in records], [6, 5])
        tidy, merge = records
        self.assertEqual((tidy["title"], tidy["author"], tidy["merged_at"]), ("Tidy", "carol", "2026-01-03T05:00:00Z"))
        self.assertEqual((merge["title"], merge["author"], merge["merged_by"]), ("Add widgets", "bob", "alice"))
        self.assertEqual((merge["provider"], merge["host"], len(merge["sha"])), ("local", "", 40))
        self.assertIsNone(merge["url"])

    def test_bot_committer_unknown(self):
        repo = make_repo(self.root / "bot")
        commit(repo, "Squash (#9)", committer=("GitHub", "noreply@github.com"))
        self.assertIsNone(local.collect(str(repo), "main", "", None, {})[0]["merged_by"])

    def test_branches_and_default(self):
        repo = make_repo(self.root / "b")
        commit(repo, "init")
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        result = local.inspect(str(repo), "", None)
        self.assertEqual(result["branches"], ["main", "origin/main"])
        self.assertEqual(result["default_branch"], "main")
        self.assertEqual(result["repository"], str(repo.resolve()))
        self.assertIsNone(result["hint"])
        git(repo, "remote", "add", "origin", "git@github.com:octo-org/widgets.git")
        self.assertEqual(local.inspect(str(repo), "", None)["hint"], "GitHub")
        self.assertTrue(local.branch_exists(str(repo), "origin/main", "", None))
        self.assertFalse(local.branch_exists(str(repo), "nope", "", None))
        self.assertFalse(local.branch_exists(str(repo), "-x", "", None))

    def test_inspect_git_calls_do_not_scale_with_branches(self):
        from unittest import mock
        from dev_monitor.providers import base
        repo = make_repo(self.root / "many")
        commit(repo, "init")
        for index in range(30):
            git(repo, "update-ref", f"refs/remotes/origin/b{index}", "HEAD")
        with mock.patch.object(base, "git", wraps=base.git) as spy:
            local.inspect(str(repo), "", None)
        self.assertLessEqual(spy.call_count, 8)

    def test_inspect_rejects_non_folder(self):
        with self.assertRaises(ProviderError):
            local.inspect("octo-org/widgets", "", None)

    def test_url_from_origin(self):
        repo = self.build()
        git(repo, "remote", "add", "origin", "https://gitlab.example.com/g/p.git")
        merge = local.collect(str(repo), "main", "", None, {})[1]
        self.assertEqual(merge["url"], "https://gitlab.example.com/g/p/-/merge_requests/5")
        git(repo, "remote", "set-url", "origin", "git@github.com:octo-org/widgets.git")
        self.assertEqual(local.collect(str(repo), "main", "", None, {})[1]["url"],
                         "https://github.com/octo-org/widgets/pull/5")

    def test_branch_without_merges(self):
        repo = make_repo(self.root / "plain")
        commit(repo, "Only direct pushes")
        self.assertEqual(local.collect(str(repo), "main", "", None, {}), [])

    def test_path_with_spaces_and_bad_bytes(self):
        repo = make_repo(self.root / "my repo")
        (repo / "f.txt").write_text("x")
        git(repo, "add", "-A")
        message = self.root / "msg.bin"
        message.write_bytes(b"Caf\xff (#3)\n")
        git(repo, "commit", "-q", "-F", str(message))
        records = local.collect(str(repo), "main", "", None, {})
        self.assertEqual(records[0]["number"], 3)
        self.assertTrue(records[0]["title"].startswith("Caf"))
        self.assertEqual(len(records[0]["title"]), 4)

    def test_read_only(self):
        repo = self.build()
        before = (git(repo, "status", "--porcelain"), sorted(os.listdir(repo / ".git")))
        local.inspect(str(repo), "", None)
        local.collect(str(repo), "main", "", None, {})
        self.assertEqual(before, (git(repo, "status", "--porcelain"), sorted(os.listdir(repo / ".git"))))


if __name__ == "__main__":
    unittest.main()
