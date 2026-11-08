import json
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from dev_monitor import auth, server
from dev_monitor.auth import Credential
from dev_monitor.providers.base import ProviderError
from dev_monitor.storage import Store
from tests.helpers import record

STATUS = {"hosts": {"github.com": [{"login": "mabid", "active": True, "state": "success"},
                                   {"login": "Muz", "active": False, "state": "success"},
                                   {"login": "expired", "active": False, "state": "error"}]}}


def gh_runner(tokens, json_ok=True):
    def run(command, **kwargs):
        if command[:3] == ["gh", "auth", "status"]:
            out = json.dumps(STATUS) if json_ok else "unknown flag: --json"
            return subprocess.CompletedProcess(command, 0 if json_ok else 1, out, "")
        if command[:3] == ["gh", "auth", "token"]:
            user = command[command.index("--user") + 1] if "--user" in command else "mabid"
            token = tokens.get(user)
            return subprocess.CompletedProcess(command, 0 if token else 1, token or "", "")
        raise AssertionError(command)
    return run


class GhAccountTests(unittest.TestCase):
    def test_lists_every_logged_in_account_active_first(self):
        accounts = auth.gh_cli_accounts(gh_runner({"mabid": "t1", "Muz": "t2"}))
        self.assertEqual(accounts, [("mabid", "t1"), ("Muz", "t2")])

    def test_old_gh_falls_back_to_the_active_token(self):
        self.assertEqual(auth.gh_cli_accounts(gh_runner({"mabid": "t1"}, json_ok=False)), [(None, "t1")])

    def test_no_gh(self):
        def missing(command, **kwargs):
            raise FileNotFoundError("gh")
        self.assertEqual(auth.gh_cli_accounts(missing), [])


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    def sources(self, provider="github", host="github.com", owner="octo", env=None, accounts=()):
        found = auth.credential_candidates(provider, host, owner, self.store, env or {}, lambda: list(accounts))
        return [credential.source for credential in found]

    def test_order_owner_token_env_host_token_then_gh_accounts(self):
        self.store.save_credential("github", "github.com", "host-wide")
        self.store.save_credential("github", "github.com", "for-octo", owner="octo")
        self.assertEqual(self.sources(env={"GITHUB_TOKEN": "e"}, accounts=[("mabid", "t1"), ("Muz", "t2")]),
                         ["saved:octo", "env:GITHUB_TOKEN", "saved", "gh:mabid", "gh:Muz"])

    def test_owner_token_only_for_its_owner(self):
        self.store.save_credential("github", "github.com", "for-octo", owner="octo")
        self.assertEqual(self.sources(owner="other"), [])

    def test_self_hosted_ignores_env_and_gh(self):
        self.store.save_credential("gitlab", "git.example.com", "mine", owner="team")
        self.assertEqual(self.sources("gitlab", "git.example.com", "team", {"GITLAB_TOKEN": "e"}, [("m", "t")]),
                         ["saved:team"])

    def test_descriptions(self):
        self.assertEqual(auth.describe(Credential("t", source="gh:Muz"), "github.com"), "gh account Muz")
        self.assertEqual(auth.describe(Credential("t", source="gh"), "github.com"), "your gh login")
        self.assertEqual(auth.describe(Credential("t", source="saved:octo"), "github.com"), "token saved for octo")
        self.assertEqual(auth.describe(Credential("t", source="saved"), "github.com"), "token saved for github.com")
        self.assertEqual(auth.describe(Credential("t", source="env:GITHUB_TOKEN"), "github.com"),
                         "GITHUB_TOKEN environment variable")
        self.assertEqual(auth.describe(None, "github.com"), "no login (public access)")


class OwnerStorageTests(unittest.TestCase):
    def test_owner_tokens_are_separate_and_case_insensitive(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            store.save_credential("github", "github.com", "a", owner="Hammerfist-Studio")
            store.save_credential("github", "github.com", "b", owner="drivenasa")
            self.assertEqual(store.saved_credential("github", "github.com", owner="hammerfist-studio").token, "a")
            store.forget_credential("github", "github.com", owner="HAMMERFIST-studio")
            self.assertIsNone(store.saved_credential("github", "github.com", owner="hammerfist-studio"))
            self.assertEqual(store.saved_credential("github", "github.com", owner="drivenasa").token, "b")

    def test_remembered_login_survives_state_rewrites(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            store.remember_login("github", "github.com", "Octo", "gh:Muz")
            store.write_state({"provider": "github"})
            self.assertEqual(Store(root).preferred_login("github", "github.com", "octo"), "gh:Muz")


def private_repo(readable_by):
    """A GitHub stand-in whose repository only `readable_by` tokens can see."""
    module = types.SimpleNamespace(NAME="github", seen=[])

    def check(credential):
        token = credential.token if credential else None
        module.seen.append(token)
        if token not in readable_by:
            raise ProviderError("GitHub could not find that repository or branch, or the token can't read it.", 404)

    def inspect(source, host, credential):
        check(credential)
        return {"repository": "octo/widgets", "default_branch": "main", "branches": ["main"],
                "display_source": "octo/widgets"}

    def branch_exists(repository, branch, host, credential):
        check(credential)
        return True

    def collect(repository, branch, host, credential, previous):
        check(credential)
        return [record()]
    module.inspect, module.branch_exists, module.collect = inspect, branch_exists, collect
    return module


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name))
        self.accounts = [("mabid", "t1"), ("Muz", "t2")]
        self.app = server.MonitorApp(self.store, None, env={}, gh_accounts=lambda: list(self.accounts))

    def tearDown(self):
        self.temporary.cleanup()

    def run_with(self, module, call, payload):
        with mock.patch("dev_monitor.providers.get", return_value=module):
            return call({"provider": "github", "source": "octo/widgets", **payload})

    def test_falls_through_to_the_gh_account_that_can_read(self):
        module = private_repo({"t2"})
        result = self.run_with(module, self.app.inspect, {})
        self.assertEqual(result["credential"], "gh account Muz")
        self.assertEqual(result["owner"], "octo")
        self.assertEqual(module.seen, ["t1", "t2"])
        module.seen.clear()
        self.run_with(module, self.app.inspect, {})
        self.assertEqual(module.seen, ["t2"], "the account that worked is tried first next time")

    def test_sync_collects_with_the_account_that_worked(self):
        module = private_repo({"t2"})
        self.run_with(module, self.app.sync, {"branch": "main", "timezone": "UTC"})
        self.assertEqual(module.seen[-1], "t2")
        self.assertEqual(self.app.state()["login"], "gh account Muz")

    def test_nobody_can_read_lists_what_was_tried(self):
        with self.assertRaises(ProviderError) as caught:
            self.run_with(private_repo(set()), self.app.inspect, {})
        message = str(caught.exception)
        self.assertIn("gh account mabid", message)
        self.assertIn("gh account Muz", message)
        self.assertIn("Use a different token", message)
        self.assertEqual(caught.exception.status, 404)

    def test_public_repo_works_without_any_login(self):
        module = private_repo({None})
        result = self.run_with(module, self.app.inspect, {})
        self.assertEqual(result["credential"], "no login (public access)")
        self.assertEqual(module.seen, ["t1", "t2", None], "logins first, then public access")

    def test_token_saved_for_owner_is_used_first(self):
        module = private_repo({"org-token"})
        self.app.save_credentials({"provider": "github", "host": "", "owner": "Octo", "token": "org-token"})
        self.assertEqual(self.run_with(module, self.app.inspect, {})["credential"], "token saved for octo")
        self.assertEqual(module.seen, ["org-token"])

    def test_bad_owner_rejected(self):
        with self.assertRaises(ProviderError):
            self.app.save_credentials({"provider": "github", "host": "", "owner": "../x", "token": "t"})


if __name__ == "__main__":
    unittest.main()
