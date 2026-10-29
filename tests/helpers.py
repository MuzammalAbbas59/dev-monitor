def record(number=1, title="Add widgets", merged_at="2026-01-01T20:00:00Z", author="alice", merged_by="bob",
           provider="github", host="github.com", url=None, sha=None, description="Body"):
    if url is None and number is not None and provider != "local":
        url = f"https://{host}/octo-org/widgets/pull/{number}"
    return {"number": number, "title": title, "description": description, "url": url, "author": author,
            "merged_by": merged_by, "merged_at": merged_at, "provider": provider, "host": host, "sha": sha}


def snapshot(records, provider="github", host="github.com", repository="octo-org/widgets", branch="main",
             timezone="UTC", synced_at="2026-01-03T00:00:00Z"):
    return {"provider": provider, "host": host, "repository": repository, "branch": branch,
            "timezone": timezone, "synced_at": synced_at, "records": records}


import os
import subprocess
from pathlib import Path

GIT_ENV = {"GIT_AUTHOR_NAME": "alice", "GIT_AUTHOR_EMAIL": "alice@example.com",
           "GIT_COMMITTER_NAME": "alice", "GIT_COMMITTER_EMAIL": "alice@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(path, *args, env=None, input=None):
    environment = {**os.environ, **GIT_ENV, **(env or {})}
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True,
                          env=environment, input=input).stdout.decode("utf-8", "replace")


def make_repo(path, branch="main"):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    return path


def commit(path, message, when="2026-01-01T10:00:00+00:00", author=None, committer=None, name=None):
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    if author:
        env.update(GIT_AUTHOR_NAME=author, GIT_AUTHOR_EMAIL=f"{author}@example.com")
    if committer:
        cname, cemail = committer if isinstance(committer, tuple) else (committer, f"{committer}@example.com")
        env.update(GIT_COMMITTER_NAME=cname, GIT_COMMITTER_EMAIL=cemail)
    file = Path(path) / (name or "file.txt")
    file.write_text(file.read_text() + "x\n" if file.exists() else "x\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message, env=env)
