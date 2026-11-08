import json
import tempfile
import unittest
from pathlib import Path

from dev_monitor import updates
from dev_monitor.providers.base import ProviderError

DAY = 24 * 60 * 60


def pypi(version, calls=None):
    def fetch(url, **kwargs):
        if calls is not None:
            calls.append(url)
        return {"info": {"version": version}}, {}
    return fetch


class VersionTests(unittest.TestCase):
    def test_newer(self):
        self.assertTrue(updates.is_newer("0.1.3", "0.1.2"))
        self.assertTrue(updates.is_newer("0.1.10", "0.1.9"))
        self.assertFalse(updates.is_newer("0.1.2", "0.1.2"))
        self.assertFalse(updates.is_newer("0.1.1", "0.1.2"))

    def test_prereleases_and_junk_are_ignored(self):
        self.assertFalse(updates.is_newer("0.2.0rc1", "0.1.2"))
        self.assertFalse(updates.is_newer("", "0.1.2"))
        self.assertFalse(updates.is_newer(None, "0.1.2"))

    def test_upgrade_command_matches_install_method(self):
        self.assertEqual(updates.upgrade_command("/Users/me/.local/pipx/venvs/dev-monitor"), "pipx upgrade dev-monitor")
        self.assertEqual(updates.upgrade_command("C:\\Users\\me\\pipx\\venvs\\dev-monitor"), "pipx upgrade dev-monitor")
        self.assertEqual(updates.upgrade_command("/home/me/.local/share/uv/tools/dev-monitor"),
                         "uv tool upgrade dev-monitor")
        self.assertEqual(updates.upgrade_command("/usr/local"), "pip install --upgrade dev-monitor")


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_check_saves_latest_and_reuses_it_for_a_day(self):
        calls = []
        self.assertEqual(updates.check(self.root, env={}, fetch=pypi("0.1.3", calls), now=1000), "0.1.3")
        self.assertEqual(updates.check(self.root, env={}, fetch=pypi("0.1.4", calls), now=1000 + DAY - 1), "0.1.3")
        self.assertEqual(len(calls), 1)
        self.assertEqual(updates.check(self.root, env={}, fetch=pypi("0.1.4", calls), now=1000 + DAY), "0.1.4")
        self.assertEqual(calls, [updates.PYPI_URL] * 2)

    def test_offline_is_silent(self):
        def offline(url, **kwargs):
            raise ProviderError("Could not reach pypi.org.", 502)
        self.assertIsNone(updates.check(self.root, env={}, fetch=offline, now=1000))

    def test_opt_out_never_contacts_pypi(self):
        calls = []
        self.assertIsNone(updates.check(self.root, env={"DEV_MONITOR_NO_UPDATE_CHECK": "1"}, fetch=pypi("9.9.9", calls)))
        self.assertEqual(calls, [])

    def test_notice_only_when_newer(self):
        (self.root / updates.CACHE).write_text(json.dumps({"checked_at": 1000, "latest": "9.0.0"}))
        notice = updates.notice(self.root, current="0.1.2", prefix="/x/pipx/venvs/dev-monitor")
        self.assertEqual(notice, {"latest": "9.0.0", "current": "0.1.2", "command": "pipx upgrade dev-monitor"})
        self.assertIsNone(updates.notice(self.root, current="9.0.0", prefix="/x"))

    def test_terminal_message(self):
        (self.root / updates.CACHE).write_text(json.dumps({"checked_at": 1000, "latest": "9.0.0"}))
        message = updates.terminal_message(self.root, env={})
        self.assertIn("Dev Monitor 9.0.0 is available", message)
        self.assertIn("upgrade dev-monitor", message)
        self.assertIsNone(updates.terminal_message(self.root, env={"DEV_MONITOR_NO_UPDATE_CHECK": "1"}))

    def test_notice_without_cache_or_with_bad_cache(self):
        self.assertIsNone(updates.notice(self.root, current="0.1.2", prefix="/x"))
        (self.root / updates.CACHE).write_text("{not json")
        self.assertIsNone(updates.notice(self.root, current="0.1.2", prefix="/x"))


if __name__ == "__main__":
    unittest.main()
