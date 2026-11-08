import re
from pathlib import Path

from . import base

NAME = "local"
GITHUB_MERGE = re.compile(r"Merge pull request #(\d+) from ")
BITBUCKET_MERGE = re.compile(r"Merged in .+ \(pull request #(\d+)\)$")
GITLAB_REFERENCE = re.compile(r"See merge request \S+!(\d+)")
SQUASH = re.compile(r"^(.*\S)\s+\(#(\d+)\)$")
BOT_NAMES = {"GitHub", "GitLab", "Bitbucket", "web-flow"}
HOST_HINTS = {"github.com": "GitHub", "gitlab.com": "GitLab", "bitbucket.org": "Bitbucket"}
FIELD, RECORD = "\x1f", "\x1e"


def _first_line(body, skip=None):
    for line in body.splitlines():
        line = line.strip()
        if line and not (skip and skip.search(line)):
            return line
    return None


def classify(subject, body, parents):
    """Return (number, title) for a merged change, or None for a direct push."""
    subject = subject.strip()
    for pattern in (GITHUB_MERGE, BITBUCKET_MERGE):
        match = pattern.match(subject)
        if match:
            return int(match.group(1)), _first_line(body) or subject
    match = GITLAB_REFERENCE.search(body)
    if match:
        return int(match.group(1)), _first_line(body, GITLAB_REFERENCE) or subject
    match = SQUASH.match(subject)
    if match:
        return int(match.group(2)), match.group(1)
    if len(parents) >= 2:
        return None, subject
    return None


def _root(source):
    source = (source or "").strip()
    path = Path(source).expanduser() if source else None
    if not path or not path.is_dir():
        raise base.ProviderError("Enter the path of a local git checkout folder.")
    return base.checkout_context(path.resolve())


def inspect(source, host, credential):
    context = _root(source)
    root = context["checkout_path"]
    names = base.git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes").split()
    names = [name for name in names if not name.endswith("/HEAD") and name != "origin"]
    heads = _local_heads(root)
    branches = ([name for name in names if name in heads] + [name for name in names if name not in heads])[:100]
    # Merges land on the main line (origin/HEAD), not on whatever feature branch is checked out.
    try:
        default = base.git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD").strip() or None
    except base.ProviderError:
        default = None
    default = default or context["current_branch"]
    remote = base.origin_remote(root)
    return {"repository": root, "default_branch": default, "branches": branches, "display_source": root,
            "hint": HOST_HINTS.get(remote[0]) if remote else None, **context}


def _local_heads(root):
    return set(base.git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())


def branch_exists(repository, branch, host, credential):
    if not branch or branch.startswith("-"):
        return False
    try:
        base.git(repository, "rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}")
    except base.ProviderError:
        return False
    return True


def _is_bot(name, email):
    return name in BOT_NAMES or email == "noreply@github.com" or (
        name == "GitHub" and email.endswith("@users.noreply.github.com"))


def _url(remote, number):
    if not remote or number is None:
        return None
    host, slug = remote
    if host == "github.com":
        return f"https://{host}/{slug}/pull/{number}"
    if "gitlab" in host:
        return f"https://{host}/{slug}/-/merge_requests/{number}"
    if host == "bitbucket.org":
        return f"https://{host}/{slug}/pull-requests/{number}"
    return None


def collect(repository, branch, host, credential, previous):
    if not branch_exists(repository, branch, host, credential):
        raise base.ProviderError(f"Branch {branch!r} does not exist in this checkout.", 404)
    output = base.git(repository, "log", "--first-parent",
                      "--format=%H%x1f%P%x1f%an%x1f%cn%x1f%ce%x1f%cI%x1f%s%x1f%b%x1e", branch, "--", timeout=300)
    remote = base.origin_remote(repository)
    pending = []
    for entry in output.split(RECORD):
        entry = entry.strip("\n")
        if not entry:
            continue
        sha, parents, author, committer, email, date, subject, body = (entry.split(FIELD, 7) + [""] * 8)[:8]
        parents = parents.split()
        classified = classify(subject, body, parents)
        if classified:
            pending.append((sha, parents, author, committer, email, date, classified))
    second_parents = [parents[1] for _, parents, *_ in pending if len(parents) >= 2]
    branch_authors = {}
    for start in range(0, len(second_parents), 500):
        shown = base.git(repository, "show", "-s", "--format=%H%x1f%an", *second_parents[start:start + 500])
        for line in shown.splitlines():
            if FIELD in line:
                sha, name = line.split(FIELD, 1)
                branch_authors[sha] = name
    records = []
    for sha, parents, author, committer, email, date, (number, title) in pending:
        if len(parents) >= 2:
            author = branch_authors.get(parents[1], author)
        records.append({"number": number, "title": title, "description": "", "url": _url(remote, number),
                        "author": author or None, "merged_by": None if _is_bot(committer, email) else committer or None,
                        "merged_at": base.utc_z(date), "provider": NAME, "host": "", "sha": sha})
    return base.sort_records(records)
