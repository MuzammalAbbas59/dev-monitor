"""Tell people when a newer release is on PyPI. Asks for the version number only, at most once a day."""
import json
import re
import sys
import time
from pathlib import Path

from . import __version__
from .providers import base
from .storage import atomic_write

PYPI_URL = "https://pypi.org/pypi/dev-monitor/json"
CACHE = "update-check.json"
DAY = 24 * 60 * 60
OPT_OUT = "DEV_MONITOR_NO_UPDATE_CHECK"
RELEASE = re.compile(r"\d+(\.\d+)*")


def is_newer(candidate, current):
    """True only for a plain release (no rc/dev tags) above the current version."""
    if not isinstance(candidate, str) or not RELEASE.fullmatch(candidate) or not RELEASE.fullmatch(current):
        return False
    return tuple(map(int, candidate.split("."))) > tuple(map(int, current.split(".")))


def upgrade_command(prefix=sys.prefix):
    location = prefix.replace("\\", "/")
    if "/pipx/venvs/" in location + "/":
        return "pipx upgrade dev-monitor"
    if "/uv/tools/" in location + "/":
        return "uv tool upgrade dev-monitor"
    return "pip install --upgrade dev-monitor"


def _cached(root):
    try:
        data = json.loads((Path(root) / CACHE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def check(root, env, fetch=base.http_json, now=None):
    """Refresh the cached latest version when it is a day old. Never raises; returns the latest known version."""
    if env.get(OPT_OUT):
        return None
    now = time.time() if now is None else now
    cached = _cached(root)
    if isinstance(cached.get("checked_at"), (int, float)) and now - cached["checked_at"] < DAY:
        return cached.get("latest")
    try:
        body, _ = fetch(PYPI_URL, provider="pypi", timeout=5)
        latest = body["info"]["version"]
        atomic_write(Path(root) / CACHE, json.dumps({"checked_at": now, "latest": latest}) + "\n")
        return latest
    except (base.ProviderError, OSError, KeyError, TypeError):
        return cached.get("latest")


def notice(root, current=__version__, prefix=sys.prefix):
    latest = _cached(root).get("latest")
    if not is_newer(latest, current):
        return None
    return {"latest": latest, "current": current, "command": upgrade_command(prefix)}


def terminal_message(root, env):
    found = None if env.get(OPT_OUT) else notice(root)
    if not found:
        return None
    return f"Dev Monitor {found['latest']} is available (you have {found['current']}). Update: {found['command']}"
