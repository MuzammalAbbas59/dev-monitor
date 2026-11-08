# Bitbucket Cloud REST 2.0. Auth uses Atlassian API tokens with scopes, sent as
# HTTP Basic "account email:token" (app passwords were removed in 2026). See
# https://support.atlassian.com/bitbucket-cloud/docs/using-api-tokens/
import base64
from urllib.parse import quote, urlencode

from . import base

NAME = "bitbucket"
API = "https://api.bitbucket.org/2.0"
HOST = "bitbucket.org"
FIELDS = "+values.description,+values.closed_on,+values.closed_by,+values.merge_commit.hash"


def _check_host(host):
    if host != HOST:
        raise base.ProviderError("Only Bitbucket Cloud (bitbucket.org) is supported.")


def _headers(credential):
    if not credential:
        return {}
    pair = f"{credential.email or ''}:{credential.token}".encode()
    return {"Authorization": "Basic " + base64.b64encode(pair).decode()}


def _get(url, credential):
    return base.http_json(url, headers=_headers(credential), provider=NAME)[0]


def inspect(source, host, credential):
    _check_host(host)
    kind, value = base.parse_hosted_source(source, host, base.SLUG)
    context = {"checkout_path": None, "current_branch": None, "checkout_status": None}
    if kind == "path":
        if not value:
            raise base.ProviderError("Enter a Bitbucket repository such as workspace/repo.")
        value, context = base.resolve_checkout(value, NAME, host, base.SLUG)
    metadata = _get(f"{API}/repositories/{value}", credential)
    repository = metadata.get("full_name") or value
    branches = _get(f"{API}/repositories/{repository}/refs/branches?pagelen=100", credential)
    return {"repository": repository, "default_branch": (metadata.get("mainbranch") or {}).get("name"),
            "branches": [branch["name"] for branch in branches.get("values", [])][:100],
            "display_source": context["checkout_path"] or repository, **context}


def branch_exists(repository, branch, host, credential):
    _check_host(host)
    try:
        _get(f"{API}/repositories/{repository}/refs/branches/{quote(branch, safe='')}", credential)
    except base.ProviderError as error:
        if error.status == 404:
            return False
        raise
    return True


def _name(user):
    user = user or {}
    return user.get("nickname") or user.get("display_name")


def _merged_at(pr, repository, credential, previous):
    """Bitbucket has no merged_at: prefer closed_on, then a known value, then the merge commit date."""
    if pr.get("closed_on"):
        return base.utc_z(pr["closed_on"])
    known = previous.get(f"#{pr['id']}")
    if known and known.get("merged_at"):
        return known["merged_at"]
    commit = (pr.get("merge_commit") or {}).get("hash")
    if commit:
        date = _get(f"{API}/repositories/{repository}/commit/{commit}", credential).get("date")
        if date:
            return base.utc_z(date)
    return base.utc_z(pr["updated_on"])


def collect(repository, branch, host, credential, previous):
    _check_host(host)
    quoted = branch.replace("\\", "\\\\").replace('"', '\\"')
    query = urlencode({"state": "MERGED", "pagelen": 50, "q": f'destination.branch.name="{quoted}"', "fields": FIELDS})
    url, records = f"{API}/repositories/{repository}/pullrequests?{query}", []
    while url:
        page = _get(url, credential)
        for pr in page.get("values", []):
            records.append({"number": pr["id"], "title": pr["title"], "description": pr.get("description") or "",
                            "url": ((pr.get("links") or {}).get("html") or {}).get("href"),
                            "author": _name(pr.get("author")), "merged_by": _name(pr.get("closed_by")),
                            "merged_at": _merged_at(pr, repository, credential, previous),
                            "provider": NAME, "host": host, "sha": None})
        url = page.get("next")
        if url and not url.startswith(API + "/"):
            raise base.ProviderError("Bitbucket returned an unexpected page link.", 502)
    return base.sort_records({record["number"]: record for record in records}.values())
