import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dev_monitor.auth import Credential, resolve_credential
from dev_monitor.storage import Store


class ResolveCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name))
        self.no_gh = mock.Mock(return_value=None)

    def tearDown(self):
        self.temporary.cleanup()

    def test_env_token_only_for_default_host(self):
        env = {"GITLAB_TOKEN": "envtok"}
        self.assertEqual(resolve_credential("gitlab", "gitlab.com", self.store, env, self.no_gh), Credential("envtok"))
        self.assertIsNone(resolve_credential("gitlab", "git.example.com", self.store, env, self.no_gh))

    def test_env_overrides_saved_on_default_host(self):
        self.store.save_credential("gitlab", "gitlab.com", "saved")
        self.assertEqual(resolve_credential("gitlab", "gitlab.com", self.store, {"GITLAB_TOKEN": "envtok"}, self.no_gh),
                         Credential("envtok"))

    def test_saved_used_for_self_hosted(self):
        self.store.save_credential("gitlab", "git.example.com", "saved")
        self.assertEqual(resolve_credential("gitlab", "git.example.com", self.store, {"GITLAB_TOKEN": "envtok"}, self.no_gh),
                         Credential("saved"))

    def test_gh_token_only_for_github_com(self):
        gh = mock.Mock(return_value="ghtok")
        self.assertIsNone(resolve_credential("github", "ghe.example.com", self.store, {}, gh))
        gh.assert_not_called()
        self.assertEqual(resolve_credential("github", "github.com", self.store, {}, gh), Credential("ghtok"))

    def test_github_order_env_then_saved_then_gh(self):
        gh = mock.Mock(return_value="ghtok")
        self.assertEqual(resolve_credential("github", "github.com", self.store, {}, gh), Credential("ghtok"))
        self.store.save_credential("github", "github.com", "saved")
        self.assertEqual(resolve_credential("github", "github.com", self.store, {}, gh), Credential("saved"))
        self.assertEqual(resolve_credential("github", "github.com", self.store, {"GITHUB_TOKEN": "env"}, gh),
                         Credential("env"))

    def test_bitbucket_needs_email_and_token(self):
        self.assertIsNone(resolve_credential("bitbucket", "bitbucket.org", self.store,
                                             {"BITBUCKET_TOKEN": "t"}, self.no_gh))
        self.assertEqual(resolve_credential("bitbucket", "bitbucket.org", self.store,
                                            {"BITBUCKET_TOKEN": "t", "BITBUCKET_EMAIL": "a@x.io"}, self.no_gh),
                         Credential("t", "a@x.io"))

    def test_repr_hides_token(self):
        self.assertNotIn("envtok", repr(Credential("envtok")))


if __name__ == "__main__":
    unittest.main()
