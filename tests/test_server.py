import http.client
import json
import socket
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

from dev_monitor import server
from dev_monitor.storage import Store
from tests.helpers import record


def fake_provider(delay=None):
    def inspect(source, host, credential):
        return {"repository": "octo-org/widgets", "default_branch": "main", "branches": ["main"],
                "display_source": "octo-org/widgets", "checkout_path": None, "current_branch": None,
                "checkout_status": None}

    def collect(repository, branch, host, credential, previous):
        if delay:
            delay.wait(5)
        return [record(title="Ship </script> widgets")]

    return types.SimpleNamespace(NAME="gitlab", inspect=inspect, collect=collect,
                                 branch_exists=lambda *args: True)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name))
        self.app = server.MonitorApp(self.store, None, env={}, gh_token=lambda: None)
        self.server, self.url = server.bind(self.app, 0)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.patch = mock.patch("dev_monitor.providers.get", return_value=fake_provider())
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.server.shutdown()
        self.server.server_close()
        self.temporary.cleanup()

    def request(self, method, path, body=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        host = f"127.0.0.1:{self.port}"
        default = {"Host": host}
        if method == "POST":
            default.update({"X-Dev-Monitor": "1", "Origin": f"http://{host}", "Content-Type": "application/json"})
        default.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in default.items():
            if value is not None:
                connection.putheader(key, value)
        if data is not None:
            connection.putheader("Content-Length", str(len(data)))
        connection.endheaders(data)
        response = connection.getresponse()
        content = response.read()
        connection.close()
        return response.status, response.getheader("Content-Type"), content

    def test_rejects_bad_host_origin_header_type_size(self):
        payload = {"provider": "gitlab", "source": "octo-org/widgets"}
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "evil.example.com"})[0], 403)
        self.assertEqual(self.request("POST", "/api/repository", payload, headers={"X-Dev-Monitor": None})[0], 403)
        self.assertEqual(self.request("POST", "/api/repository", payload, headers={"Origin": "http://evil.example.com"})[0], 403)
        self.assertEqual(self.request("POST", "/api/repository", payload, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/api/repository", raw=b"{" + b" " * 16400 + b"}")[0], 413)

    def test_pick_folder_returns_chosen_path(self):
        with mock.patch("dev_monitor.picker.pick_folder", return_value="/Users/me/repo") as pick:
            status, _, body = self.request("POST", "/api/pick-folder", {})
        self.assertEqual((status, json.loads(body)), (200, {"path": "/Users/me/repo"}))
        pick.assert_called_once()

    def test_pick_folder_needs_local_page_headers(self):
        with mock.patch("dev_monitor.picker.pick_folder") as pick:
            status = self.request("POST", "/api/pick-folder", {}, headers={"Origin": "http://evil.example.com"})[0]
        self.assertEqual(status, 403)
        pick.assert_not_called()

    def test_state_carries_update_notice(self):
        notice = {"latest": "9.0.0", "current": "0.1.2", "command": "pipx upgrade dev-monitor"}
        with mock.patch("dev_monitor.updates.notice", return_value=notice):
            self.assertEqual(json.loads(self.request("GET", "/api/state")[2])["update"], notice)

    def test_no_update_notice_when_opted_out(self):
        self.app.env = {"DEV_MONITOR_NO_UPDATE_CHECK": "1"}
        with mock.patch("dev_monitor.updates.notice", return_value={"latest": "9.0.0"}):
            self.assertIsNone(json.loads(self.request("GET", "/api/state")[2])["update"])

    def test_state_says_whether_folder_picker_exists(self):
        with mock.patch("dev_monitor.picker.available", return_value=False):
            self.assertFalse(json.loads(self.request("GET", "/api/state")[2])["folder_picker"])

    def test_state_never_contains_token(self):
        status, _, _ = self.request("POST", "/api/credentials", {"provider": "gitlab", "host": "git.example.com",
                                                                 "token": "sekret-123"})
        self.assertEqual(status, 200)
        status, _, body = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertNotIn(b"sekret", body)
        self.assertTrue(json.loads(body)["tokens"]["gitlab:git.example.com"])

    def test_credentials_save_and_forget(self):
        self.request("POST", "/api/credentials", {"provider": "gitlab", "host": "", "token": "abc"})
        self.assertEqual(self.store.saved_credential("gitlab", "gitlab.com").token, "abc")
        status, _, body = self.request("POST", "/api/credentials", {"provider": "gitlab", "host": "", "token": None})
        self.assertEqual(status, 200)
        self.assertNotIn("gitlab:gitlab.com", json.loads(body)["tokens"])
        self.assertEqual(self.request("POST", "/api/credentials", {"provider": "bitbucket", "token": "t"})[0], 400)
        self.assertEqual(self.request("POST", "/api/credentials", {"provider": "local", "token": "t"})[0], 400)

    def test_sync_then_root_embeds_snapshot(self):
        status, _, body = self.request("POST", "/api/sync", {"provider": "gitlab", "host": "", "source": "octo-org/widgets",
                                                            "branch": "", "timezone": "UTC"})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["count"], 1)
        status, content_type, page = self.request("GET", "/")
        self.assertIn(b"Ship \\u003c/script\\u003e widgets", page)
        status, content_type, _ = self.request("GET", "/merges.csv")
        self.assertEqual((status, content_type.split(";")[0]), (200, "text/csv"))
        state = json.loads(self.request("GET", "/api/state")[2])
        self.assertEqual((state["provider"], state["host"], state["branch"]), ("gitlab", "gitlab.com", "main"))

    def test_concurrent_sync_409(self):
        gate = threading.Event()
        self.patch.stop()
        self.patch = mock.patch("dev_monitor.providers.get", return_value=fake_provider(gate))
        self.patch.start()
        payload = {"provider": "gitlab", "source": "octo-org/widgets", "timezone": "UTC"}
        results = []
        worker = threading.Thread(target=lambda: results.append(self.request("POST", "/api/sync", payload)))
        worker.start()
        for _ in range(100):
            if self.app.refresh_lock.locked():
                break
            threading.Event().wait(0.02)
        self.assertEqual(self.request("POST", "/api/sync", payload)[0], 409)
        gate.set()
        worker.join()
        self.assertEqual(results[0][0], 200)

    def test_unknown_route_404(self):
        self.assertEqual(self.request("GET", "/etc/passwd")[0], 404)
        self.assertEqual(self.request("POST", "/api/nope", {})[0], 404)

    def test_bind_falls_back_when_port_busy(self):
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        busy = blocker.getsockname()[1]
        other = server.MonitorApp(Store(Path(self.temporary.name) / "other"), None, env={}, gh_token=lambda: None)
        try:
            bound, url = server.bind(other, busy)
            self.assertGreater(bound.server_port, busy)
            self.assertEqual(url, f"http://127.0.0.1:{bound.server_port}/")
            bound.server_close()
        finally:
            blocker.close()

    def test_bind_reuses_existing_instance(self):
        twin = server.MonitorApp(self.store, None, env={}, gh_token=lambda: None)
        bound, url = server.bind(twin, self.port)
        self.assertIsNone(bound)
        self.assertEqual(url, f"http://127.0.0.1:{self.port}/")

    def test_failed_sync_reports_error_and_keeps_state(self):
        self.request("POST", "/api/sync", {"provider": "gitlab", "source": "octo-org/widgets", "timezone": "UTC"})
        before = self.request("GET", "/api/state")[2]
        status, _, body = self.request("POST", "/api/sync", {"provider": "gitlab", "source": "octo-org/widgets",
                                                            "timezone": "Mars/Base"})
        self.assertEqual(status, 400)
        self.assertIn("IANA", json.loads(body)["error"])
        self.assertEqual(json.loads(before)["checked_at"], json.loads(self.request("GET", "/api/state")[2])["checked_at"])


if __name__ == "__main__":
    unittest.main()
