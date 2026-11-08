import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from dev_monitor import __version__, cli
from tests.helpers import commit, make_repo


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_sync_command_local(self):
        repo = make_repo(self.root / "repo")
        commit(repo, "Tidy (#6)")
        out = self.root / "out"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = cli.main(["sync", "--provider", "local", "--repo", str(repo), "--branch", "main",
                             "--out", str(out), "--data-dir", str(self.root / "data")])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads((out / "records.json").read_text())["records"]), 1)
        self.assertIn("Checked Local folder: 1 merged PRs into main. Updated snapshot.", stdout.getvalue())

    def test_sync_command_accepts_quoted_path(self):
        repo = make_repo(self.root / "my repo")
        commit(repo, "Tidy (#6)")
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["sync", "--provider", "local", "--repo", f'"{repo}"', "--branch", "main",
                             "--out", str(self.root / "out"), "--data-dir", str(self.root / "data")])
        self.assertEqual(code, 0)

    def test_sync_command_error_exit_1(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = cli.main(["sync", "--provider", "local", "--repo", str(self.root / "missing"),
                             "--out", str(self.root / "out"), "--data-dir", str(self.root / "data")])
        self.assertEqual(code, 1)
        self.assertIn("local git checkout", stderr.getvalue())

    def test_version(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as context:
            cli.main(["--version"])
        self.assertEqual(context.exception.code, 0)
        self.assertEqual(stdout.getvalue().strip(), f"dev-monitor {__version__}")


if __name__ == "__main__":
    unittest.main()
