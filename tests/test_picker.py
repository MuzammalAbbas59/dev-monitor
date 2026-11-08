import subprocess
import unittest

from dev_monitor import picker
from dev_monitor.providers.base import ProviderError


def runner(stdout="", returncode=0, calls=None):
    def run(command, **kwargs):
        if calls is not None:
            calls.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout.encode("utf-8"), b"")
    return run


def which(*available):
    return lambda name: f"/usr/bin/{name}" if name in available else None


class PickerTests(unittest.TestCase):
    def test_macos_uses_choose_folder(self):
        calls = []
        path = picker.pick_folder("darwin", runner("/Users/me/my repo/\n", calls=calls), which())
        self.assertEqual(path, "/Users/me/my repo")
        self.assertEqual(calls[0][0], "osascript")
        self.assertIn("choose folder", " ".join(calls[0]))

    def test_cancel_returns_none(self):
        for platform, tools in (("darwin", ()), ("win32", ()), ("linux", ("zenity",))):
            self.assertIsNone(picker.pick_folder(platform, runner(returncode=1), which(*tools)), platform)

    def test_windows_uses_folder_browser_dialog(self):
        calls = []
        path = picker.pick_folder("win32", runner("C:\\Users\\Zoë\\repo\r\n", calls=calls), which())
        self.assertEqual(path, "C:\\Users\\Zoë\\repo")
        self.assertEqual(calls[0][0], "powershell")
        self.assertIn("FolderBrowserDialog", " ".join(calls[0]))

    def test_linux_prefers_zenity_then_kdialog(self):
        calls = []
        picker.pick_folder("linux", runner("/home/me/repo\n", calls=calls), which("zenity", "kdialog"))
        self.assertEqual(calls[-1][0], "zenity")
        picker.pick_folder("linux", runner("/home/me/repo\n", calls=calls), which("kdialog"))
        self.assertEqual(calls[-1][0], "kdialog")

    def test_linux_without_a_picker(self):
        self.assertFalse(picker.available("linux", which()))
        with self.assertRaisesRegex(ProviderError, "paste the folder path"):
            picker.pick_folder("linux", runner(), which())

    def test_root_folder_keeps_its_slash(self):
        self.assertEqual(picker.pick_folder("darwin", runner("/\n"), which()), "/")


if __name__ == "__main__":
    unittest.main()
