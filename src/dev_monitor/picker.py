"""Open the operating system's own folder window, so nobody has to type a checkout path."""
import shutil
import subprocess
import sys

from .providers.base import ProviderError

PROMPT = "Choose a git checkout folder"
MACOS = ["osascript", "-e", "activate", "-e", f'POSIX path of (choose folder with prompt "{PROMPT}")']
WINDOWS = ["powershell", "-NoProfile", "-STA", "-Command",
           "Add-Type -AssemblyName System.Windows.Forms; "
           "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
           "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
           f"$dialog.Description = '{PROMPT}'; $dialog.ShowNewFolderButton = $false; "
           "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true}; "
           "if ($dialog.ShowDialog($owner) -eq 'OK') { $dialog.SelectedPath }"]
LINUX = {"zenity": ["zenity", "--file-selection", "--directory", f"--title={PROMPT}"],
         "kdialog": ["kdialog", "--getexistingdirectory", ".", "--title", PROMPT]}


def _command(platform, which):
    if platform == "darwin":
        return MACOS
    if platform == "win32":
        return WINDOWS
    for tool, command in LINUX.items():
        if which(tool):
            return command
    return None


def available(platform=sys.platform, which=shutil.which):
    return _command(platform, which) is not None


def pick_folder(platform=sys.platform, run=subprocess.run, which=shutil.which):
    """Return the chosen folder, or None when the person cancels."""
    command = _command(platform, which)
    if command is None:
        raise ProviderError("No folder window is available here. Install zenity, or paste the folder path.", 501)
    try:
        result = run(command, capture_output=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        raise ProviderError("The folder window could not be opened. Paste the folder path instead.", 500) from None
    path = result.stdout.decode("utf-8", "replace").strip()
    if result.returncode != 0 or not path:
        return None
    trimmed = path.rstrip("/\\")
    return path if not trimmed or trimmed.endswith(":") else trimmed  # keep "/" and "C:\\" whole
