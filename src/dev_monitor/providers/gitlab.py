import re
from urllib.parse import quote, urlencode

from . import base

NAME = "gitlab"
SLUG = re.compile(r"[\w.-]+(/[\w.-]+)+\Z")


def _api(host):
    return f"https://{host}/api/v4"


def _headers(credential):
    return {"PRIVATE-TOKEN": credential.token} if credential else {}


def _project(slug):
    return quote(slug, safe="")


def inspect(source, host, credential):
    kind, value = base.parse_hosted_source(source, host, SLUG)
    context = {"checkout_path": None, "current_branch": None, "checkout_status": None}
    if kind == "path":
        if not value:
            raise base.ProviderError("Enter a GitLab project such as group/project.")
        value, context = base.resolve_checkout(value, NAME, host, SLUG)
    headers = _headers(credential)
    metadata = base.http_json(f"{_api(host)}/projects/{_project(value)}", headers=headers, provider=NAME)[0]
    repository = metadata.get("path_with_namespace") or value
    branches = base.http_json(f"{_api(host)}/projects/{_project(repository)}/repository/branches?per_page=100",
                              headers=headers, provider=NAME)[0]
    return {"repository": repository, "default_branch": metadata.get("default_branch"),
            "branches": [branch["name"] for branch in branches][:100],
            "display_source": context["checkout_path"] or repository, **context}


def branch_exists(repository, branch, host, credential):
    try:
        base.http_json(f"{_api(host)}/projects/{_project(repository)}/repository/branches/{quote(branch, safe='')}",
                       headers=_headers(credential), provider=NAME)
    except base.ProviderError as error:
        if error.status == 404:
            return False
        raise
    return True


def _login(user):
    return (user or {}).get("username")


def collect(repository, branch, host, credential, previous):
    records, page = [], "1"
    while page:
        query = urlencode({"page": page, "per_page": 100, "state": "merged", "target_branch": branch})
        items, headers = base.http_json(f"{_api(host)}/projects/{_project(repository)}/merge_requests?{query}",
                                        headers=_headers(credential), provider=NAME)
        for item in items:
            if not item.get("merged_at"):
                continue
            records.append({"number": item["iid"], "title": item["title"], "description": item.get("description") or "",
                            "url": item.get("web_url"), "author": _login(item.get("author")),
                            "merged_by": _login(item.get("merge_user")) or _login(item.get("merged_by")),
                            "merged_at": base.utc_z(item["merged_at"]), "provider": NAME, "host": host, "sha": None})
        page = headers.get("x-next-page", "")
    return base.sort_records({record["number"]: record for record in records}.values())
