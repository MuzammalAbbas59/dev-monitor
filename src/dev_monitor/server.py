import http.client
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__, providers, reports, sync
from .auth import gh_cli_token, resolve_credential
from .providers.base import LABELS, ProviderError, normalize_host
from .storage import DEFAULT_HOSTS

EXPORTS = {"/records.json": "application/json", "/merges.csv": "text/csv", "/REPORT.md": "text/markdown"}
EMPTY = {"provider": "", "host": "", "repository": "", "branch": "", "timezone": "UTC", "synced_at": None, "records": []}
FALLBACK_PORTS = 10


class MonitorApp:
    def __init__(self, store, checkout, env=os.environ, gh_token=gh_cli_token):
        self.store = store
        self.checkout = Path(checkout).expanduser().resolve() if checkout else None
        self.env = env
        self._gh_token = gh_token
        self._gh_cache = None
        self.refresh_lock = threading.Lock()
        self.state_lock = threading.Lock()

    def gh_token(self):
        # gh is slow to spawn; ask once per process.
        if self._gh_cache is None:
            self._gh_cache = (self._gh_token() or "",)
        return self._gh_cache[0] or None

    def credential(self, provider, host):
        return resolve_credential(provider, host, self.store, self.env, self.gh_token)

    def profile_directory(self, metadata=None):
        profile = (metadata or self.store.read_state()).get("profile")
        return self.store.profile_dir(profile) if isinstance(profile, str) and len(profile) == 32 else None

    def snapshot(self):
        directory = self.profile_directory()
        return (directory and sync.read_snapshot(directory)) or dict(EMPTY)

    def token_flags(self):
        flags = self.store.credential_flags()
        for provider, host in DEFAULT_HOSTS.items():
            if self.credential(provider, host):
                flags[f"{provider}:{host}"] = True
        return flags

    def state(self):
        with self.state_lock:
            metadata = self.store.read_state()
            snapshot = self.snapshot()
        return {"local_app": True, "tool_id": self.store.tool_id, "version": __version__,
                "provider": snapshot["provider"] or metadata.get("provider", ""), "host": snapshot["host"],
                "repository": snapshot["repository"], "branch": snapshot["branch"], "timezone": snapshot["timezone"],
                "checked_at": metadata.get("checked_at"), "source": metadata.get("source", ""),
                "default_branch": metadata.get("default_branch"), "checkout_path": metadata.get("checkout_path"),
                "current_branch": metadata.get("current_branch"), "checkout_status": metadata.get("checkout_status"),
                "default_checkout": str(self.checkout) if self.checkout else None,
                "local_hint": metadata.get("local_hint"), "tokens": self.token_flags()}

    def _target(self, payload):
        provider = payload.get("provider")
        if not isinstance(provider, str):
            raise ProviderError("Choose GitHub, GitLab, Bitbucket, or Local folder.")
        module = providers.get(provider)
        host = payload.get("host")
        if host is not None and not isinstance(host, str):
            raise ProviderError("Enter only the server address, such as git.example.com.")
        host = normalize_host(provider, host)
        source = payload.get("source", "")
        if not isinstance(source, str) or len(source) > 4096:
            raise ProviderError("Enter a repository name, a repository URL, or a local checkout folder.")
        if not source.strip() and self.checkout:
            source = str(self.checkout)
        return provider, module, host, source

    def inspect(self, payload):
        provider, module, host, source = self._target(payload)
        result = module.inspect(source, host, self.credential(provider, host))
        return {**result, "provider": provider, "host": host}

    def sync(self, payload):
        if not self.refresh_lock.acquire(blocking=False):
            raise ProviderError("A refresh is already running. Wait for it to finish.", 409)
        try:
            display_timezone = sync.validate_timezone(payload.get("timezone", "UTC"))
            provider, module, host, source = self._target(payload)
            credential = self.credential(provider, host)
            info = module.inspect(source, host, credential)
            requested = payload.get("branch") or ""
            if not isinstance(requested, str):
                raise ProviderError("Enter a valid target branch.")
            branch = requested.strip() or info.get("current_branch") or info.get("default_branch")
            if not branch:
                raise ProviderError("This repository has no default branch. Enter a target branch.")
            branch = sync.validate_branch(branch)
            if not module.branch_exists(info["repository"], branch, host, credential):
                raise ProviderError(f"Target branch {branch!r} is unavailable in {info['repository']}.", 404)
            profile = self.store.profile_id(provider, host, info["repository"], branch)
            snapshot, _ = sync.sync_to_directory(provider, host, info["repository"], branch, display_timezone,
                                                 credential, self.store.profile_dir(profile))
            checked_at = sync.now_z()
            with self.state_lock:
                self.store.write_state({"provider": provider, "host": host, "source": info.get("display_source", source),
                                        "repository": info["repository"], "default_branch": info.get("default_branch"),
                                        "checkout_path": info.get("checkout_path"),
                                        "current_branch": info.get("current_branch"),
                                        "checkout_status": info.get("checkout_status"),
                                        "local_hint": info.get("hint"), "profile": profile, "checked_at": checked_at})
            return {"ok": True, "repository": snapshot["repository"], "branch": snapshot["branch"],
                    "checked_at": checked_at, "count": len(snapshot["records"])}
        finally:
            self.refresh_lock.release()

    def save_credentials(self, payload):
        provider = payload.get("provider")
        if provider not in DEFAULT_HOSTS:
            raise ProviderError("Tokens are only used for GitHub, GitLab, and Bitbucket.")
        host = normalize_host(provider, payload.get("host"))
        if provider == "bitbucket" and host != DEFAULT_HOSTS["bitbucket"]:
            raise ProviderError("Only Bitbucket Cloud (bitbucket.org) is supported.")
        token = payload.get("token")
        if token is None:
            self.store.forget_credential(provider, host)
        else:
            if not isinstance(token, str) or not token.strip() or len(token) > 4096 or any(c.isspace() for c in token.strip()):
                raise ProviderError("Paste the token exactly as shown when you created it.")
            email = payload.get("email")
            if provider == "bitbucket" and (not isinstance(email, str) or "@" not in email or len(email) > 320):
                raise ProviderError("Bitbucket tokens need your Atlassian account email.")
            self.store.save_credential(provider, host, token.strip(), email.strip() if provider == "bitbucket" else None)
        return {"ok": True, "tokens": self.token_flags()}

    def content(self, path):
        with self.state_lock:
            if path in ("/", "/index.html"):
                return reports.render_dashboard(self.snapshot()).encode(), "text/html"
            if path not in EXPORTS:
                raise ProviderError("Not found.", 404)
            directory = self.profile_directory()
            target = directory / path[1:] if directory else None
            if not target or not target.exists():
                raise ProviderError("Refresh a repository to generate this export.", 404)
            return target.read_bytes(), EXPORTS[path]


class MonitorHandler(BaseHTTPRequestHandler):
    server_version = "dev-monitor"

    def log_message(self, format, *args):
        pass

    def validate_host(self):
        hosts = self.headers.get_all("Host", [])
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if len(hosts) != 1 or hosts[0] not in allowed:
            raise ProviderError("Use the local monitor URL on 127.0.0.1.", 403)

    def send_content(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, payload):
        self.send_content(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json")

    def do_GET(self):
        try:
            self.validate_host()
            path = urlsplit(self.path).path
            if path == "/api/state":
                self.send_json(200, self.server.app.state())
            else:
                self.send_content(200, *self.server.app.content(path))
        except ProviderError as error:
            self.send_json(error.status, {"error": str(error)})
        except (OSError, ValueError, KeyError):
            self.send_json(500, {"error": "The local files could not be read. Check disk access and try again."})

    def read_payload(self):
        if self.headers.get("X-Dev-Monitor") != "1" or self.headers.get("Origin") != "http://" + self.headers["Host"]:
            raise ProviderError("Requests must come from the local dashboard.", 403)
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            raise ProviderError("Send an application/json request.", 415)
        if self.headers.get("Transfer-Encoding"):
            raise ProviderError("Use a fixed-length JSON request.", 400)
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise ProviderError("A JSON request body is required.", 411) from None
        if not 0 < length <= 16384:
            raise ProviderError("The request body is too large or empty.", 413)
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            raise ProviderError("The request body must be valid JSON.") from None
        if not isinstance(payload, dict):
            raise ProviderError("The request body must be a JSON object.")
        return payload

    def do_POST(self):
        try:
            self.validate_host()
            payload = self.read_payload()
            routes = {"/api/repository": self.server.app.inspect, "/api/sync": self.server.app.sync,
                      "/api/credentials": self.server.app.save_credentials}
            handler = routes.get(urlsplit(self.path).path)
            if not handler:
                raise ProviderError("Not found.", 404)
            self.send_json(200, handler(payload))
        except ProviderError as error:
            self.send_json(error.status, {"error": str(error)})
        except (OSError, ValueError, KeyError):
            self.send_json(500, {"error": "The local files could not be updated. Check disk access and try again."})

    def do_OPTIONS(self):
        self.send_json(405, {"error": "Only local dashboard requests are supported."})


def _existing_instance(port, tool_id):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/api/state", headers={"Host": f"127.0.0.1:{port}"})
        response = connection.getresponse()
        state = json.loads(response.read(1 << 20))
        return response.status == 200 and state.get("local_app") is True and state.get("tool_id") == tool_id
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def bind(app, port):
    """Bind 127.0.0.1:port, reuse a running instance of this data dir, or try the next ports."""
    last_error = None
    for candidate in range(port, port + FALLBACK_PORTS + 1) if port else [0]:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), MonitorHandler)
        except OSError as error:
            last_error = error
            if candidate == port and _existing_instance(port, app.store.tool_id):
                return None, f"http://127.0.0.1:{port}/"
            continue
        server.daemon_threads = True
        server.app = app
        return server, f"http://127.0.0.1:{server.server_port}/"
    raise OSError(f"No free port between {port} and {port + FALLBACK_PORTS}: {last_error}")
