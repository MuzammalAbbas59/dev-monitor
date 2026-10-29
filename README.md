# Dev Monitor

See how many pull requests merge into a branch each day, who authors them, and who merges them. Works with GitHub, GitLab, Bitbucket Cloud, or a plain local git checkout, on Windows, macOS, and Linux.

Everything runs on your own computer: a small local web page, no account, no database, and no server to host.

## Install

You need Python 3.10 or newer. Install with [pipx](https://pipx.pypa.io/) or [uv](https://docs.astral.sh/uv/):

```sh
pipx install dev-monitor
# or
uv tool install dev-monitor
```

Until the first PyPI release, install from GitHub:

```sh
pipx install git+https://github.com/mabid/dev-monitor
```

## Run

```sh
dev-monitor
```

Your browser opens at `http://127.0.0.1:8765/`. If that port is busy, the next free one is used, and the URL is printed in the terminal. Then:

1. Pick a **Source**: GitHub, GitLab, Bitbucket, or Local folder.
2. Enter the repository: `OWNER/REPO`, a repository URL, or a local checkout folder.
3. Click **Load repository**, check **Monitor merges into**, then click **Refresh**.

The dashboard shows merged PRs per day, top authors, top mergers, and a searchable merge log. Filter by date range, timezone, author, merger, or text. Exports (`records.json`, `merges.csv`, `REPORT.md`, and a self-contained `index.html`) are available for the active repository.

Options: `--port 9000`, `--no-open`, `--data-dir PATH`, `--checkout PATH` (the folder used when the repository box is left empty).

## Sources and tokens

| Source | Token | Where to create it | Permissions |
|---|---|---|---|
| GitHub | Uses `gh` if you're logged in, else paste a token | [Fine-grained token](https://github.com/settings/personal-access-tokens/new) | Read-only: Contents, Pull requests |
| GitLab | Not needed for public projects | User settings → Access tokens | `read_api` |
| Bitbucket Cloud | Not needed for public repositories. API token plus your Atlassian email | [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens) | `read:repository:bitbucket`, `read:pullrequest:bitbucket` |
| Local folder | None | | |

Paste a token into the dashboard once. It is saved only on your computer, in `credentials.json` inside the data folder, readable only by you.

You can also use environment variables: `GITHUB_TOKEN`, `GITLAB_TOKEN`, or `BITBUCKET_EMAIL` with `BITBUCKET_TOKEN`.

**Tokens only go to their own host.** Environment variables and `gh` are used only for `github.com`, `gitlab.com`, and `bitbucket.org`. A self-hosted GitLab or GitHub Enterprise server (enter it in the **Server** field) only receives a token you saved for that exact server. Self-hosted servers must use https.

A local checkout path also works with GitHub, GitLab, and Bitbucket. Dev Monitor reads the checkout's `origin` remote and current branch, then collects exact PR data from the host.

## Local folder mode

Reads git history only. It never fetches, checks out, or writes anything in your repository. On the selected branch (local or remote-tracking, such as `origin/main`), it counts:

- merge commits, such as "Merge pull request #12 …", "Merged in … (pull request #12)", "See merge request group/project!12", or any other merge, and
- squash commits that end in a PR number, such as `Fix login (#42)`.

Direct pushes are not counted. Authors come from the merged branch, or from the commit for squash merges. "Merged by" is the committer, so it is approximate, and merges made through a hosting site's web UI show as *Unknown / unavailable*. Run `git fetch` yourself to see newer merges.

## One-shot reports

Write the four report files to a folder without starting the dashboard, for example from a script or CI:

```sh
dev-monitor sync --provider github --repo OWNER/REPO --out reports/
dev-monitor sync --provider gitlab --host git.example.com --repo group/project --branch main --timezone Asia/Karachi
dev-monitor sync --provider local --repo . --branch origin/main --open
```

Running it again in the same folder keeps the PR titles and descriptions as first seen.

## Where data lives

| OS | Folder |
|---|---|
| Windows | `%APPDATA%\dev-monitor` |
| macOS | `~/Library/Application Support/dev-monitor` |
| Linux | `$XDG_DATA_HOME/dev-monitor` (default `~/.local/share/dev-monitor`) |

Each repository and branch pair has its own snapshot under `profiles/`. Delete the folder to start over.

## Privacy

- The page and API listen on `127.0.0.1` only and reject requests from other sites.
- PR data goes from the git host to your computer and nowhere else.
- Exports contain PR titles and descriptions, so treat them as being as sensitive as the repository itself.

## Limits

One repository and one target branch at a time. Merged PRs only: no open PRs, deployments, or CI stats. Refresh is manual. Bitbucket Server and Data Center are not supported.

## Development

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m dev_monitor --data-dir /tmp/dm --port 8799
```

MIT licensed.
