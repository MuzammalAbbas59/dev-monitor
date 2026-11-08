# Dev Monitor

[![PyPI](https://img.shields.io/pypi/v/dev-monitor)](https://pypi.org/project/dev-monitor/) [![CI](https://github.com/MuzammalAbbas59/dev-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/MuzammalAbbas59/dev-monitor/actions/workflows/ci.yml)

See how many pull requests merge into a branch each day, who authors them, and who merges them. Works with GitHub, GitLab, Bitbucket Cloud, or a plain local git checkout, on Windows, macOS, and Linux.

Everything runs on your own computer: a small local web page, no account, no database, and no server to host.

## Install

Dev Monitor is installed with [pipx](https://pipx.pypa.io/), which puts the `dev-monitor` command on your PATH without touching your other Python packages.

**1. Get pipx** (skip if `pipx --version` already works):

| OS | Commands |
|---|---|
| macOS ([Homebrew](https://brew.sh)) | `brew install pipx` then `pipx ensurepath` |
| Windows | `py -m pip install --user pipx` then `py -m pipx ensurepath` |
| Ubuntu / Debian | `sudo apt install pipx` then `pipx ensurepath` |
| Fedora | `sudo dnf install pipx` then `pipx ensurepath` |
| Other Linux | `python3 -m pip install --user pipx` then `python3 -m pipx ensurepath` |

Then **close and reopen your terminal** so the new PATH takes effect.

No Python yet? On macOS, Homebrew installs it along with pipx. On Windows, install Python 3.10 or newer from [python.org](https://www.python.org/downloads/) and tick "Add python.exe to PATH". On Linux, use your package manager.

**2. Install Dev Monitor:**

```sh
pipx install dev-monitor
```

**3. Check it worked:**

```sh
dev-monitor --version
```

If the terminal says `command not found` (or `not recognized` on Windows), open a new terminal window, or run `pipx ensurepath` again.

<details>
<summary>Prefer uv?</summary>

[uv](https://docs.astral.sh/uv/) downloads its own Python, so you don't need one installed first.

```sh
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

uv tool install dev-monitor
```

</details>

To try the latest unreleased code instead:

```sh
pipx install git+https://github.com/MuzammalAbbas59/dev-monitor
```

## Run

```sh
dev-monitor
```

Your browser opens at `http://127.0.0.1:8765/`. If that port is busy, the next free one is used, and the URL is printed in the terminal. Then:

1. Pick a **Source**: GitHub, GitLab, Bitbucket, or Local folder.
2. Enter the repository: `OWNER/REPO`, a repository URL, or a local checkout folder. For a local folder, click **Browse…** to pick it instead of typing the path (on Linux this needs `zenity` or `kdialog`).
3. Click **Load repository**, check **Monitor merges into**, then click **Refresh**.

The dashboard shows merged PRs per day, top authors, top mergers, and a searchable merge log. Filter by date range, timezone, author, merger, or text. Exports (`records.json`, `merges.csv`, `REPORT.md`, and a self-contained `index.html`) are available for the active repository.

Options: `--port 9000`, `--no-open`, `--data-dir PATH`, `--checkout PATH` (the folder used when the repository box is left empty), `--no-update-check`.

When a newer release is out, a notice at the top of the dashboard (and in the terminal) shows the command to update, such as `pipx upgrade dev-monitor`. Dev Monitor never updates itself.

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
- Once a day, Dev Monitor asks pypi.org for the latest version number, to show the update notice. Nothing about you or your repositories is sent. Turn it off with `--no-update-check` or `DEV_MONITOR_NO_UPDATE_CHECK=1`.

## Limits

One repository and one target branch at a time. Merged PRs only: no open PRs, deployments, or CI stats. Refresh is manual. Bitbucket Server and Data Center are not supported.

## Upgrade or remove

```sh
pipx upgrade dev-monitor      # uv: uv tool upgrade dev-monitor
pipx uninstall dev-monitor    # uv: uv tool uninstall dev-monitor
```

Uninstalling leaves your saved data and tokens in place. Delete the data folder (see *Where data lives*) to remove them too.

## Development

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m dev_monitor --data-dir /tmp/dm --port 8799
```

To release, bump `__version__` in `src/dev_monitor/__init__.py`, commit, then push a tag such as `v0.1.4`. GitHub Actions publishes it to PyPI.

MIT licensed.
