import http.client
import json
import re
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .. import __version__
from ..storage import DEFAULT_HOSTS

LABELS = {"github": "GitHub", "gitlab": "GitLab", "bitbucket": "Bitbucket", "local": "Local folder"}
SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
HOST = re.compile(r"[a-z0-9.-]+(:[0-9]{1,5})?\Z")


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


# urllib copies Authorization/PRIVATE-TOKEN to redirect targets, so redirects are refused outright.
_OPENER = urllib.request.build_opener(_RefuseRedirects)


class ProviderError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _reset_time(headers):
    reset = headers.get("x-ratelimit-reset") or headers.get("ratelimit-reset")
    if reset and reset.isdigit():
        return datetime.fromtimestamp(int(reset)).strftime("%H:%M")
    retry = headers.get("retry-after")
    if retry and retry.isdigit():
        return datetime.fromtimestamp(datetime.now().timestamp() + int(retry)).strftime("%H:%M")
    return "later"


def http_json(url, *, headers=None, provider, timeout=30, data=None):
    """GET (or POST when data is given) JSON. Errors never include request headers."""
    label = LABELS.get(provider, provider)
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                     headers={"User-Agent": f"dev-monitor/{__version__}",
                                              "Accept": "application/json", **(headers or {})})
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body, {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as error:
        response_headers = {key.lower(): value for key, value in (error.headers or {}).items()}
        error.close()
        if 300 <= error.code < 400:
            raise ProviderError(f"{label} redirected the request to another address. Check the server address, "
                                f"or whether a login proxy sits in front of the API.", 502) from None
        if error.code == 401:
            raise ProviderError(f"{label} rejected the token. Create a new one and save it again.", 401) from None
        if error.code == 429 or (error.code == 403 and (response_headers.get("x-ratelimit-remaining") == "0"
                                                        or "retry-after" in response_headers)):
            raise ProviderError(f"{label} rate limit reached. Try again after {_reset_time(response_headers)}.", 429) from None
        if error.code == 404:
            raise ProviderError(f"{label} could not find that repository or branch, or the token can't read it.", 404) from None
        if error.code == 403:
            raise ProviderError(f"{label} denied access. Check that the token can read this repository.", 403) from None
        raise ProviderError(f"{label} returned an error ({error.code}). Try again.", 502) from None
    except urllib.error.URLError as error:
        if isinstance(error.reason, ssl.SSLCertVerificationError):
            raise ProviderError(f"{urlsplit(url).netloc} sent a certificate this computer doesn't trust. A company proxy "
                                f"or a self-signed server certificate usually causes this.", 502) from None
        if isinstance(error.reason, TimeoutError):
            raise ProviderError(f"{label} took too long to respond. Try again.", 504) from None
        raise ProviderError(f"Could not reach {urlsplit(url).netloc}. Check the server address and your connection.", 502) from None
    except (ValueError, UnicodeError):
        raise ProviderError(f"{label} returned an unexpected response. Try again.", 502) from None
    except TimeoutError:
        raise ProviderError(f"{label} took too long to respond. Try again.", 504) from None
    except (OSError, http.client.HTTPException):
        raise ProviderError(f"The connection to {urlsplit(url).netloc} dropped before {label} finished responding. "
                            f"Try again.", 502) from None


def normalize_host(provider, host):
    if provider == "local":
        return ""
    if not host or not host.strip():
        return DEFAULT_HOSTS[provider]
    host = host.strip()
    if "://" in host:
        parsed = urlsplit(host)
        if parsed.scheme != "https":
            raise ProviderError("Self-hosted servers must use https.")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment or "@" in parsed.netloc:
            raise ProviderError("Enter only the server address, such as git.example.com.")
        host = parsed.netloc
    host = host.lower().rstrip("/")
    if not HOST.fullmatch(host):
        raise ProviderError("Enter only the server address, such as git.example.com.")
    return host


def _strip(slug):
    slug = slug.strip("/")
    return slug[:-4] if slug.endswith(".git") else slug


def _remote_parts(url):
    """Return (host, slug) for https, ssh:// and scp-like git remote URLs."""
    if "://" in url:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme == "https" and parsed.port:
            host = f"{host}:{parsed.port}"
        return host, _strip(parsed.path)
    match = re.fullmatch(r"(?:[^@/]+@)?([^:/]+):(.+)", url)
    if match:
        return match.group(1).lower(), _strip(match.group(2))
    return None


def unquote_source(source):
    """Drop quotes around a pasted path or URL; Windows "Copy as path" adds them."""
    stripped = (source or "").strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        return stripped[1:-1].strip()
    return source


def parse_hosted_source(source, host, slug_pattern):
    source = (source or "").strip()
    if not source:
        return "path", ""
    remote = None
    if source.startswith(("https://", "http://", "ssh://")) or re.match(r"[^@/\s]+@[^:/\s]+:", source):
        remote = _remote_parts(source)
    if remote:
        remote_host, slug = remote
        if remote_host != host:
            raise ProviderError(f"That URL is not on {host}. Change the server field or the URL.")
        if not slug_pattern.fullmatch(slug):
            raise ProviderError("That URL does not point at a repository.")
        return "slug", slug
    if slug_pattern.fullmatch(source) and not Path(source).expanduser().is_dir():
        return "slug", source
    path = Path(source).expanduser()
    if path.is_dir():
        return "path", str(path.resolve())
    raise ProviderError("Enter a repository name, a repository URL, or an existing local checkout folder.")


def git(path, *args, timeout=60):
    try:
        result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError:
        raise ProviderError("git is not installed. Install it and try again.") from None
    except subprocess.TimeoutExpired:
        raise ProviderError("git took too long to respond.", 504) from None
    if result.returncode:
        message = result.stderr.decode("utf-8", "replace").strip() or "git failed."
        raise ProviderError(message[-2000:])
    return result.stdout.decode("utf-8", "replace")


def origin_remote(path):
    try:
        url = git(path, "remote", "get-url", "origin").strip()
    except ProviderError:
        return None
    return _remote_parts(url) if url else None


def checkout_context(path):
    root = git(path, "rev-parse", "--show-toplevel").strip()
    try:
        branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD").strip()
    except ProviderError:
        branch = ""
    return {"checkout_path": str(Path(root).resolve()), "current_branch": branch or None,
            "checkout_status": "Attached branch" if branch else "Detached HEAD"}


def resolve_checkout(path, provider, host, slug_pattern):
    """Resolve a checkout path to its origin slug on the chosen host."""
    context = checkout_context(path)
    remote = origin_remote(context["checkout_path"])
    if not remote:
        raise ProviderError("This checkout has no origin remote. Enter the repository name instead.")
    remote_host, slug = remote
    if remote_host != host or not slug_pattern.fullmatch(slug):
        raise ProviderError(f"This checkout's origin is on {remote_host}, not {host}. "
                            f"Choose the matching source or change the server field.")
    return slug, context


def utc_z(value):
    """Normalize an ISO timestamp to UTC 'YYYY-MM-DDTHH:MM:SSZ'."""
    from datetime import timezone
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_key(record):
    return f"#{record['number']}" if record.get("number") is not None else f"sha:{record.get('sha')}"


def sort_records(records):
    return sorted(records, key=lambda record: (record["merged_at"], record["number"] or 0), reverse=True)
