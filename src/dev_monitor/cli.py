import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__, providers, server, sync, updates
from .auth import explain_rejection, resolve_credential
from .providers.base import LABELS, ProviderError, normalize_host, unquote_source
from .storage import Store, default_data_dir


def _common(parser):
    parser.add_argument("--data-dir", type=Path, help="Folder for saved snapshots, settings, and tokens")


def serve(arguments):
    store = Store(arguments.data_dir or default_data_dir())
    if arguments.no_update_check:
        os.environ[updates.OPT_OUT] = "1"
    app = server.MonitorApp(store, arguments.checkout)
    try:
        bound, url = server.bind(app, arguments.port)
    except OSError as error:
        print(f"Could not start Dev Monitor: {error}. Choose another --port.", file=sys.stderr)
        return 1
    if bound is None:
        print(f"Dev Monitor is already running: {url}")
        if not arguments.no_open:
            webbrowser.open(url)
        return 0
    print(f"Dev Monitor: {url}", flush=True)
    message = updates.terminal_message(store.root, os.environ)
    if message:
        print(message, flush=True)
    # Refresh the daily version check in the background; the dashboard reads the result.
    threading.Thread(target=updates.check, args=(store.root, os.environ), daemon=True).start()
    if not arguments.no_open:
        webbrowser.open(url)
    try:
        bound.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        bound.server_close()
    return 0


def run_sync(arguments):
    store = Store(arguments.data_dir or default_data_dir())
    credential = None
    try:
        module = providers.get(arguments.provider)
        host = normalize_host(arguments.provider, arguments.host)
        display_timezone = sync.validate_timezone(arguments.timezone)
        credential = resolve_credential(arguments.provider, host, store)
        info = module.inspect(unquote_source(arguments.repo), host, credential)
        branch = sync.validate_branch(arguments.branch or info.get("default_branch") or info.get("current_branch") or "", arguments.provider)
        if not module.branch_exists(info["repository"], branch, host, credential):
            raise ProviderError(f"Target branch {branch!r} is unavailable in {info['repository']}.", 404)
        snapshot, changed = sync.sync_to_directory(arguments.provider, host, info["repository"], branch,
                                                   display_timezone, credential, arguments.out)
    except ProviderError as error:
        print(explain_rejection(error, credential, arguments.provider), file=sys.stderr)
        return 1
    print(f"Checked {LABELS[arguments.provider]}: {len(snapshot['records'])} merged PRs into {branch}. "
          f"{'Updated' if changed else 'Unchanged'} snapshot.")
    if arguments.open:
        webbrowser.open((Path(arguments.out) / "index.html").resolve().as_uri())
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["sync"]:
        parser = argparse.ArgumentParser(prog="dev-monitor sync",
                                         description="Collect merged PRs once and write the reports to a folder.")
        parser.add_argument("--provider", required=True, choices=providers.NAMES)
        parser.add_argument("--repo", required=True, help="OWNER/REPO, repository URL, or local checkout path")
        parser.add_argument("--host", help="Self-hosted server address (GitHub Enterprise or GitLab)")
        parser.add_argument("--branch", help="Branch PRs were merged into (default: the repository's default branch)")
        parser.add_argument("--timezone", default="UTC", help="IANA timezone for report dates")
        parser.add_argument("--out", type=Path, default=Path("."), help="Output folder (default: current folder)")
        parser.add_argument("--open", action="store_true", help="Open the generated dashboard")
        _common(parser)
        return run_sync(parser.parse_args(argv[1:]))
    parser = argparse.ArgumentParser(prog="dev-monitor",
                                     description="Start the local Dev Monitor dashboard. Use `dev-monitor sync -h` for one-shot reports.")
    parser.add_argument("--version", action="version", version=f"dev-monitor {__version__}")
    parser.add_argument("--port", type=int, default=8765, help="Local port (default 8765; tries the next 10 if busy)")
    parser.add_argument("--checkout", type=Path, help="Checkout used when the repository box is left empty")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser")
    parser.add_argument("--no-update-check", action="store_true",
                        help=f"Never ask PyPI for the latest version (or set {updates.OPT_OUT}=1)")
    _common(parser)
    arguments = parser.parse_args(argv)
    if not 1 <= arguments.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    return serve(arguments)
