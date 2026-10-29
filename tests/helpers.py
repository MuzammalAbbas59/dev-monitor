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
