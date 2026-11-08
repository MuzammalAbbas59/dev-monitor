import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

DEFAULT_HOSTS = {"github": "github.com", "gitlab": "gitlab.com", "bitbucket": "bitbucket.org"}


def default_data_dir(platform=sys.platform, env=os.environ, home=None):
    home = Path(home) if home is not None else Path.home()
    if platform == "win32":
        base = env.get("APPDATA")
        return (Path(base) if base else home / "AppData" / "Roaming") / "dev-monitor"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "dev-monitor"
    base = env.get("XDG_DATA_HOME")
    return (Path(base) if base else home / ".local" / "share") / "dev-monitor"


def atomic_write(path, text, mode=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with open(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser()
        self.tool_id = hashlib.sha256(("dev-monitor:" + str(self.root.resolve())).encode()).hexdigest()
        self.state_file = self.root / "state.json"
        self.credentials_file = self.root / "credentials.json"
        self.logins_file = self.root / "logins.json"

    def profile_id(self, provider, host, repository, branch):
        repository = repository if provider == "local" else repository.lower()
        identity = json.dumps([provider, host, repository, branch], separators=(",", ":"))
        return hashlib.sha256(identity.encode()).hexdigest()[:32]

    def profile_dir(self, profile_id):
        return self.root / "profiles" / profile_id

    def read_state(self):
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def write_state(self, state):
        atomic_write(self.state_file, json.dumps(state, ensure_ascii=False, indent=2) + "\n")

    def _credentials(self):
        try:
            return json.loads(self.credentials_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def _write_credentials(self, credentials):
        self.root.mkdir(parents=True, exist_ok=True)
        # mkstemp creates the file 0600, so the token is never readable by others, even briefly.
        descriptor, temporary = tempfile.mkstemp(prefix="credentials.", suffix=".tmp", dir=self.root)
        try:
            with open(descriptor, "w", encoding="utf-8") as handle:
                json.dump(credentials, handle, indent=2)
            os.replace(temporary, self.credentials_file)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        os.chmod(self.credentials_file, 0o600)

    @staticmethod
    def _key(provider, host, owner=None):
        # Owners are case-insensitive on GitHub, GitLab and Bitbucket.
        return f"{provider}:{host}:{owner.lower()}" if owner else f"{provider}:{host}"

    def saved_credential(self, provider, host, owner=None):
        """The token saved for exactly this owner (or, with no owner, for the whole host)."""
        from .auth import Credential
        entry = self._credentials().get(self._key(provider, host, owner))
        if not entry:
            return None
        return Credential(entry["token"], entry.get("email"), source=f"saved:{owner.lower()}" if owner else "saved")

    def save_credential(self, provider, host, token, email=None, owner=None):
        credentials = self._credentials()
        credentials[self._key(provider, host, owner)] = {"token": token, "email": email}
        self._write_credentials(credentials)

    def forget_credential(self, provider, host, owner=None):
        credentials = self._credentials()
        if credentials.pop(self._key(provider, host, owner), None) is not None:
            self._write_credentials(credentials)

    def _logins(self):
        try:
            data = json.loads(self.logins_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def preferred_login(self, provider, host, owner):
        """Which login last worked for this owner, such as "gh:octocat". Never a token."""
        return self._logins().get(self._key(provider, host, owner)) if owner else None

    def remember_login(self, provider, host, owner, source):
        if not owner:
            return
        logins = self._logins()
        if logins.get(self._key(provider, host, owner)) != source:
            logins[self._key(provider, host, owner)] = source
            atomic_write(self.logins_file, json.dumps(logins, indent=2) + "\n")

    def credential_flags(self):
        return {key: True for key in self._credentials()}
