import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import providers, reports
from .providers.base import ProviderError, record_key

EXPORTS = ("index.html", "merges.csv", "REPORT.md", "records.json")


def validate_timezone(name):
    if not isinstance(name, str) or not name or len(name) > 256:
        raise ProviderError("Use an IANA timezone such as UTC or America/New_York.")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ProviderError("Use an IANA timezone such as UTC or America/New_York.") from None
    return name


INVALID_REF = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]|\.\.|@\{|//|/\.|^/|/$|\.lock$|\.lock/|\.$|^@$")


def validate_branch(branch, provider="local"):
    """Validate a branch name; only the Local folder source shells out to git."""
    branch = branch.strip() if isinstance(branch, str) else ""
    if not branch or len(branch) > 255 or branch.startswith("-"):
        raise ProviderError("Enter a valid target branch.")
    if provider != "local":
        if INVALID_REF.search(branch):
            raise ProviderError(f"{branch!r} is not a valid branch name.")
        return branch
    try:
        result = subprocess.run(["git", "check-ref-format", "--branch", branch], capture_output=True, timeout=10, check=False)
    except FileNotFoundError:
        raise ProviderError("git is not installed. Install it and try again.") from None
    if result.returncode:
        raise ProviderError(f"{branch!r} is not a valid branch name.")
    return branch


def now_z():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_snapshot(provider, host, repository, branch, display_timezone, credential, previous):
    """Collect records, keeping titles and descriptions as first observed for the same repo and branch."""
    identity = {"provider": provider, "host": host, "repository": repository, "branch": branch}
    same = bool(previous) and all(previous.get(key) == value for key, value in identity.items())
    known = {record_key(item): item for item in previous.get("records", [])} if same else {}
    records = providers.get(provider).collect(repository, branch, host, credential, known)
    for item in records:
        saved = known.get(record_key(item))
        if saved:
            item["title"], item["description"] = saved["title"], saved["description"]
    snapshot = {**identity, "timezone": display_timezone, "records": records}
    unchanged = same and previous.get("timezone") == display_timezone and previous.get("records") == records
    snapshot["synced_at"] = previous["synced_at"] if unchanged and previous.get("synced_at") else now_z()
    return snapshot


def read_snapshot(directory):
    try:
        return json.loads((Path(directory) / "records.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def sync_to_directory(provider, host, repository, branch, display_timezone, credential, directory):
    directory = Path(directory)
    snapshot = build_snapshot(provider, host, repository, branch, display_timezone, credential,
                              read_snapshot(directory))
    directory.mkdir(parents=True, exist_ok=True)
    changed = []
    with tempfile.TemporaryDirectory(prefix=".dev-monitor-", dir=directory) as staging:
        reports.write_exports(snapshot, Path(staging))
        for name in EXPORTS:
            staged, target = Path(staging) / name, directory / name
            if target.exists() and target.read_bytes() == staged.read_bytes():
                continue
            _replace(staged, target)
            changed.append(name)
    return snapshot, changed


def _replace(staged, target, attempts=5):
    """Windows refuses to replace a file another program holds open; retry briefly, then say which file."""
    for attempt in range(attempts):
        try:
            os.replace(staged, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise ProviderError(f"{target.name} is open in another program, such as Excel. "
                                    f"Close it, then refresh again.", 423) from None
            time.sleep(0.2)
