import importlib

from .base import ProviderError

NAMES = ("github", "gitlab", "bitbucket", "local")


def get(name):
    if name not in NAMES:
        raise ProviderError("Choose GitHub, GitLab, Bitbucket, or Local folder.")
    return importlib.import_module(f"{__name__}.{name}")
