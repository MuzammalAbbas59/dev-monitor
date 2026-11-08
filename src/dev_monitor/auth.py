import json
import os
import subprocess
from dataclasses import dataclass, field

from .providers.base import LABELS, ProviderError
from .storage import DEFAULT_HOSTS

ENVIRONMENT_TOKENS = {"github": "GITHUB_TOKEN", "gitlab": "GITLAB_TOKEN", "bitbucket": "BITBUCKET_TOKEN"}


@dataclass(frozen=True)
class Credential:
    token: str
    email: str | None = None
    source: str = field(default="saved", compare=False)

    def __repr__(self):
        return "Credential(***)"


def gh_cli_token():
    try:
        result = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    token = result.stdout.strip()
    return token if result.returncode == 0 and token else None


def _gh(run, *args):
    result = run(["gh", *args], capture_output=True, text=True, timeout=10, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def gh_cli_accounts(run=subprocess.run):
    """Every github.com account gh is logged in to, as (login, token), the active one first."""
    try:
        status = _gh(run, "auth", "status", "--hostname", "github.com", "--json", "hosts")
        if status is None:  # gh older than 2.58 has no --json; use the active login only
            token = _gh(run, "auth", "token", "--hostname", "github.com")
            return [(None, token)] if token else []
        entries = json.loads(status).get("hosts", {}).get("github.com", [])
        entries = sorted((entry for entry in entries if entry.get("state") == "success"), key=lambda e: not e.get("active"))
        accounts = []
        for entry in entries:
            token = _gh(run, "auth", "token", "--hostname", "github.com", "--user", entry["login"])
            if token:
                accounts.append((entry["login"], token))
        return accounts
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, AttributeError):
        return []


def credential_candidates(provider, host, owner, store, env=os.environ, gh_accounts=gh_cli_accounts):
    """Logins to try, best first. Env tokens and gh apply only to the public default host."""
    default_host = host == DEFAULT_HOSTS.get(provider)
    found = []
    if owner:
        found.append(store.saved_credential(provider, host, owner))
    if default_host:
        variable = ENVIRONMENT_TOKENS.get(provider, "")
        token = env.get(variable)
        if token and provider != "bitbucket":
            found.append(Credential(token, source=f"env:{variable}"))
        elif token and env.get("BITBUCKET_EMAIL"):
            found.append(Credential(token, env["BITBUCKET_EMAIL"], source=f"env:{variable}"))
    found.append(store.saved_credential(provider, host))
    if default_host and provider == "github":
        found.extend(Credential(token, source=f"gh:{login}" if login else "gh") for login, token in gh_accounts())
    return [credential for credential in found if credential]


def resolve_credential(provider, host, store, env=os.environ, gh_token=gh_cli_token):
    """The first login to try, for one-shot use."""
    def accounts():
        token = gh_token()
        return [(None, token)] if token else []
    found = credential_candidates(provider, host, None, store, env, accounts)
    return found[0] if found else None


def describe(credential, host):
    """Name a login for people, without the token."""
    if credential is None:
        return "no login (public access)"
    kind, _, detail = credential.source.partition(":")
    if kind == "gh":
        return f"gh account {detail}" if detail else "your gh login"
    if kind == "env":
        return f"{detail} environment variable"
    return f"token saved for {detail or host}"


def explain_rejection(error, credential, provider):
    """Point at the real token source when a host rejects a token the user didn't paste."""
    if error.status != 401 or credential is None:
        return error
    label = LABELS.get(provider, provider)
    if credential.source.startswith("env:"):
        variable = credential.source[4:]
        return ProviderError(f"{label} rejected the token in the {variable} environment variable. "
                             f"Update or unset {variable}, then restart dev-monitor.", 401)
    if credential.source.startswith("gh"):
        return ProviderError(f"{label} rejected your gh login. Run `gh auth login` again, or save a token here.", 401)
    return error
