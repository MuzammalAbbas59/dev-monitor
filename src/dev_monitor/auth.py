import os
import subprocess
from dataclasses import dataclass

from .storage import DEFAULT_HOSTS

ENVIRONMENT_TOKENS = {"github": "GITHUB_TOKEN", "gitlab": "GITLAB_TOKEN", "bitbucket": "BITBUCKET_TOKEN"}


@dataclass(frozen=True)
class Credential:
    token: str
    email: str | None = None

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
        if token and provider == "bitbucket":
            email = env.get("BITBUCKET_EMAIL")
            if email:
                return Credential(token, email)
        elif token:
            return Credential(token)
    saved = store.saved_credential(provider, host)
    if saved:
        return saved
    if default_host and provider == "github":
        token = gh_token()
        if token:
            return Credential(token)
    return None
