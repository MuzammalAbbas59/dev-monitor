import json
from urllib.parse import quote

from . import base

NAME = "github"
QUERY = """
query($owner: String!, $name: String!, $branch: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 100, after: $cursor, states: MERGED, baseRefName: $branch,
      orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        number title body url mergedAt
        author { login }
        mergedBy { login }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def _rest(host):
    return "https://api.github.com" if host == "github.com" else f"https://{host}/api/v3"


def _graphql(host):
    return "https://api.github.com/graphql" if host == "github.com" else f"https://{host}/api/graphql"


def _headers(credential):
    return {"Authorization": f"Bearer {credential.token}"} if credential else {}


def _get(url, credential):
    return base.http_json(url, headers=_headers(credential), provider=NAME)[0]


def inspect(source, host, credential):
    kind, value = base.parse_hosted_source(source, host, base.SLUG)
    context = {"checkout_path": None, "current_branch": None, "checkout_status": None}
    if kind == "path":
        if not value:
            raise base.ProviderError("Enter a GitHub repository such as OWNER/REPO.")
        value, context = base.resolve_checkout(value, NAME, host, base.SLUG)
    metadata = _get(f"{_rest(host)}/repos/{value}", credential)
    repository = metadata.get("full_name") or value
    branches = _get(f"{_rest(host)}/repos/{repository}/branches?per_page=100", credential)
    return {"repository": repository, "default_branch": metadata.get("default_branch"),
            "branches": [branch["name"] for branch in branches][:100],
            "display_source": context["checkout_path"] or repository, **context}


def branch_exists(repository, branch, host, credential):
    try:
        _get(f"{_rest(host)}/repos/{repository}/branches/{quote(branch, safe='')}", credential)
    except base.ProviderError as error:
        if error.status == 404:
            return False
        raise
    return True


def collect(repository, branch, host, credential, previous):
    if credential is None:
        raise base.ProviderError("GitHub needs a token. Create one with read access to the repository and save it.", 401)
    owner, name = repository.split("/", 1)
    records, cursor = [], None
    while True:
        payload = json.dumps({"query": QUERY, "variables": {"owner": owner, "name": name,
                                                             "branch": branch, "cursor": cursor}}).encode()
        response = base.http_json(_graphql(host), headers=_headers(credential), provider=NAME, data=payload)[0]
        if response.get("errors"):
            message = "; ".join(error.get("message", "") for error in response["errors"])[:500]
            raise base.ProviderError(f"GitHub returned an error: {message}", 502)
        repository_data = (response.get("data") or {}).get("repository")
        if repository_data is None:
            raise base.ProviderError("GitHub could not find that repository or branch, or the token can't read it.", 404)
        page = repository_data["pullRequests"]
        for node in page["nodes"]:
            if not node.get("mergedAt"):
                continue
            records.append({"number": node["number"], "title": node["title"], "description": node["body"] or "",
                            "url": node["url"], "author": (node["author"] or {}).get("login"),
                            "merged_by": (node["mergedBy"] or {}).get("login"),
                            "merged_at": base.utc_z(node["mergedAt"]), "provider": NAME, "host": host, "sha": None})
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return base.sort_records({record["number"]: record for record in records}.values())
