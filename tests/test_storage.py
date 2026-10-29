import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from dev_monitor.storage import Store, default_data_dir


class DefaultDataDirTests(unittest.TestCase):
    def test_default_data_dir_per_platform(self):
        self.assertEqual(default_data_dir("win32", {"APPDATA": r"C:\Users\a\AppData\Roaming"}),
                         Path(r"C:\Users\a\AppData\Roaming") / "dev-monitor")
        self.assertEqual(default_data_dir("darwin", {}, home=Path("/h")),
                         Path("/h/Library/Application Support/dev-monitor"))
        self.assertEqual(default_data_dir("linux", {"XDG_DATA_HOME": "/x"}), Path("/x/dev-monitor"))
        self.assertEqual(default_data_dir("linux", {}, home=Path("/h")), Path("/h/.local/share/dev-monitor"))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_profile_id_stable_and_case_rules(self):
        first = self.store.profile_id("github", "github.com", "Octo-Org/Widgets", "main")
        self.assertEqual(first, self.store.profile_id("github", "github.com", "octo-org/widgets", "main"))
        self.assertEqual(len(first), 32)
        self.assertNotEqual(self.store.profile_id("local", "", "/tmp/Repo", "main"),
                            self.store.profile_id("local", "", "/tmp/repo", "main"))
        self.assertEqual(self.store.profile_dir(first), self.root / "profiles" / first)

    def test_state_roundtrip_and_missing(self):
        self.assertEqual(self.store.read_state(), {})
        self.store.write_state({"provider": "gitlab", "profile": "a" * 32})
        self.assertEqual(Store(self.root).read_state(), {"provider": "gitlab", "profile": "a" * 32})

    @unittest.skipIf(sys.platform == "win32", "POSIX permissions")
    def test_credentials_file_permissions(self):
        self.store.save_credential("github", "github.com", "tok")
        mode = stat.S_IMODE(os.stat(self.root / "credentials.json").st_mode)
        self.assertEqual(mode, 0o600)

    def test_credentials_save_forget_flags(self):
        self.store.save_credential("gitlab", "git.example.com", "tok")
        self.assertEqual(self.store.credential_flags(), {"gitlab:git.example.com": True})
        self.assertEqual(self.store.saved_credential("gitlab", "git.example.com").token, "tok")
        self.store.forget_credential("gitlab", "git.example.com")
        self.assertEqual(self.store.credential_flags(), {})
        self.assertIsNone(self.store.saved_credential("gitlab", "git.example.com"))


if __name__ == "__main__":
    unittest.main()
