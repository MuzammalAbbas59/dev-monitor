import csv
import io
import json
from collections import Counter
from datetime import datetime
from importlib import resources
from pathlib import Path
from zoneinfo import ZoneInfo

from .storage import atomic_write

UNKNOWN = "Unknown / unavailable"
PLACEHOLDER = "__MONITOR_DATA__"


def merge_time(record, zone):
    return datetime.fromisoformat(record["merged_at"].replace("Z", "+00:00")).astimezone(zone)


def embed_json(snapshot):
    encoded = json.dumps(snapshot, ensure_ascii=False)
    for character, escape in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                              ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        encoded = encoded.replace(character, escape)
    return encoded


def render_dashboard(snapshot):
    template = resources.files("dev_monitor").joinpath("dashboard.html").read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise ValueError(f"dashboard.html must contain exactly one {PLACEHOLDER} placeholder")
    return template.replace(PLACEHOLDER, embed_json(snapshot))


def spreadsheet_safe(value):
    """Stop spreadsheets from evaluating text cells as formulas."""
    value = "" if value is None else str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def csv_report(snapshot):
    zone = ZoneInfo(snapshot["timezone"])
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["PR number", "Title", "Description", "URL", "Author", "Merged by",
                     "Merged at (UTC)", "Merged at (display timezone)", "Display timezone", "Provider"])
    for record in snapshot["records"]:
        writer.writerow(["" if record["number"] is None else record["number"], spreadsheet_safe(record["title"]),
                         spreadsheet_safe(record["description"]), record["url"] or "",
                         spreadsheet_safe(record["author"] or UNKNOWN), spreadsheet_safe(record["merged_by"] or UNKNOWN),
                         record["merged_at"],
                         merge_time(record, zone).isoformat(), snapshot["timezone"], record["provider"]])
    return output.getvalue()


def markdown(value):
    return (str(value).replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;")
            .replace("\r", " ").replace("\n", " "))


def reference(record):
    label = f"#{record['number']}" if record["number"] is not None else (record.get("sha") or "")[:7]
    return f"[{label}]({record['url']})" if record["url"] else label


def markdown_report(snapshot):
    zone = ZoneInfo(snapshot["timezone"])
    records = snapshot["records"]
    repository = snapshot["repository"]
    if snapshot["provider"] != "local" and snapshot["host"]:
        repository = f"[{repository}](https://{snapshot['host']}/{repository})"
    lines = ["# Dev Monitor", "",
             f"Repository: {repository} · Provider: {snapshot['provider']} · "
             f"Base branch: `{snapshot['branch']}` · Dates: `{snapshot['timezone']}`", "",
             f"Snapshot generated: {snapshot['synced_at']}", "",
             f"Total merged PR count: **{len(records)}**", "",
             "Counts describe merged PR activity. PR authors and people performing merges are recorded separately.", ""]
    breakdowns = [
        ("Counts by merge date", "Merge date", Counter(merge_time(r, zone).date().isoformat() for r in records), True),
        ("Counts by PR author", "PR author", Counter(r["author"] or UNKNOWN for r in records), False),
        ("Counts by person merging", "Merged by", Counter(r["merged_by"] or UNKNOWN for r in records), False),
    ]
    for title, label, counts, by_date in breakdowns:
        lines.extend([f"## {title}", "", f"| {label} | Count |", "| --- | ---: |"])
        entries = sorted(counts.items(), reverse=True) if by_date else sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        lines.extend(f"| {markdown(name)} | {count} |" for name, count in entries)
        lines.append("")
    lines.extend(["## Latest 100 merges", "", "| Merged at | PR | Title | Author | Merged by |",
                  "| --- | --- | --- | --- | --- |"])
    for record in records[:100]:
        lines.append(f"| {merge_time(record, zone).isoformat()} | {reference(record)} | {markdown(record['title'])} | "
                     f"{markdown(record['author'] or UNKNOWN)} | {markdown(record['merged_by'] or UNKNOWN)} |")
    lines.extend(["", "Full merge history and descriptions are available in `records.json`, `merges.csv`, and `index.html`.", ""])
    return "\n".join(lines)


def write_exports(snapshot, directory):
    directory = Path(directory)
    outputs = {
        "merges.csv": csv_report(snapshot),
        "REPORT.md": markdown_report(snapshot),
        "index.html": render_dashboard(snapshot),
        "records.json": json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
    }
    changed = []
    for name, content in outputs.items():
        target = directory / name
        if target.exists() and target.read_bytes() == content.encode("utf-8"):
            continue
        atomic_write(target, content)
        changed.append(name)
    return changed
