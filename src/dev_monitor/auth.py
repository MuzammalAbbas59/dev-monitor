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


def resolve_credential(provider, host, store, env=os.environ, gh_token=gh_cli_token):
    """Env tokens and gh apply only to the public default host; others need a saved token."""
    default_host = host == DEFAULT_HOSTS.get(provider)
    if default_host:
        token = env.get(ENVIRONMENT_TOKENS.get(provider, ""))
        variable = ENVIRONMENT_TOKENS.get(provider, "")
        if token and provider == "bitbucket":
            email = env.get("BITBUCKET_EMAIL")
            if email:
                return Credential(token, email, source=f"env:{variable}")
        elif token:
            return Credential(token, source=f"env:{variable}")
    saved = store.saved_credential(provider, host)
    if saved:
        return saved
    if default_host and provider == "github":
        token = gh_token()
        if token:
            return Credential(token, source="gh")
    return None


def explain_rejection(error, credential, provider):
    """Point at the real token source when a host rejects a token the user didn't paste."""
    if error.status != 401 or credential is None:
        return error
    label = LABELS.get(provider, provider)
    if credential.source.startswith("env:"):
        variable = credential.source[4:]
        return ProviderError(f"{label} rejected the token in the {variable} environment variable. "
                             f"Update or unset {variable}, then restart dev-monitor.", 401)
    if credential.source == "gh":
        return ProviderError(f"{label} rejected your gh login. Run `gh auth login` again, or save a token here.", 401)
    return error
