#!/usr/bin/env python3
"""Render GitHub-style contribution heatmaps for a whole organization.

Aggregates default-branch commits of every repository in the organization
(private ones included, as long as the token can read them) into per-day
counts for the last 52 weeks, then writes two SVGs (light / dark).

Data source: GET /repos/{owner}/{repo}/stats/commit_activity
  - 52 weeks, each with 7 per-day counts, weeks start Sunday 00:00 UTC
  - GitHub computes the stats lazily and answers 202 until ready → retried
  - day boundaries are fixed by the API (UTC), so they cannot be shifted to JST;
    only the "updated" footer date uses JST

Only aggregate numbers are published. Repository names never appear in the
output, so private repositories stay private.

Env:
  GITHUB_TOKEN  token able to read every repository of the org (required)
  ORG           organization login (default: nexa-eng)
  OUT_DIR       output directory (default: profile)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ORG = os.environ.get("ORG", "nexa-eng")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT_DIR = os.environ.get("OUT_DIR", "profile")
API = "https://api.github.com"

# The profile repository itself is updated by this script every day; counting
# it would paint a fake 1-commit streak.
EXCLUDED_REPOS = {".github"}

STATS_RETRIES = 12
STATS_RETRY_SLEEP_SEC = 3
WEEKS = 52
CELL = 11
GAP = 3
STEP = CELL + GAP
LEFT_LABEL_W = 30
TOP_LABEL_H = 18
FOOTER_H = 26
PAD = 6
JST = timezone(timedelta(hours=9))

THEMES = {
    "light": {
        "text": "#57606a",
        "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
    },
    "dark": {
        "text": "#8b949e",
        "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
    },
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAY_LABELS = {1: "Mon", 3: "Wed", 5: "Fri"}


def api_get(path: str) -> tuple[int, object]:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"{ORG}-activity-heatmap",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read()
            return res.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"GitHub API {err.code} for {path}: {detail}") from err


def list_repos() -> list[str]:
    names: list[str] = []
    page = 1
    while True:
        status, data = api_get(f"/orgs/{ORG}/repos?type=all&per_page=100&page={page}")
        if not data:
            break
        for repo in data:
            if repo.get("fork") or repo["name"] in EXCLUDED_REPOS:
                continue
            names.append(repo["name"])
        if len(data) < 100:
            break
        page += 1
    return names


def commit_activity(repo: str) -> list[dict]:
    """Return the 52-week list, or [] when the repo has no commits in range."""
    for _ in range(STATS_RETRIES):
        status, data = api_get(f"/repos/{ORG}/{repo}/stats/commit_activity")
        if status == 202:
            time.sleep(STATS_RETRY_SLEEP_SEC)
            continue
        if status == 204 or not data:
            return []
        return data
    print(f"warning: stats for {repo} not ready after retries; skipped", file=sys.stderr)
    return []


def aggregate(repos: list[str]) -> tuple[dict[int, list[int]], int]:
    weeks: dict[int, list[int]] = {}
    active_repos = 0
    for repo in repos:
        rows = commit_activity(repo)
        if any(row["total"] for row in rows):
            active_repos += 1
        for row in rows:
            bucket = weeks.setdefault(row["week"], [0] * 7)
            for i, n in enumerate(row["days"]):
                bucket[i] += n
    return weeks, active_repos


def level_thresholds(values: list[int]) -> list[int]:
    """Quartiles of the non-zero days → boundaries for levels 1..4."""
    nonzero = sorted(v for v in values if v > 0)
    if not nonzero:
        return [1, 2, 3, 4]
    def q(p: float) -> int:
        return nonzero[min(len(nonzero) - 1, int(p * len(nonzero)))]
    return [1, max(2, q(0.25)), max(3, q(0.5)), max(4, q(0.75))]


def level_of(n: int, th: list[int]) -> int:
    if n <= 0:
        return 0
    for lvl, bound in enumerate(th[1:], start=1):
        if n < bound:
            return lvl
    return 4


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(weeks: dict[int, list[int]], active_repos: int, theme: dict, today: datetime) -> str:
    week_starts = sorted(weeks)[-WEEKS:]
    all_values = [n for w in week_starts for n in weeks[w]]
    th = level_thresholds(all_values)
    total = sum(all_values)

    width = PAD + LEFT_LABEL_W + len(week_starts) * STEP + PAD
    height = PAD + TOP_LABEL_H + 7 * STEP + FOOTER_H + PAD
    text = theme["text"]
    levels = theme["levels"]
    font = "font-family=\"-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif\" font-size=\"10\""

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{esc(ORG)} commit activity, last 52 weeks: {total} commits">',
        f'<title>{esc(ORG)} — {total} commits in the last 52 weeks</title>',
    ]

    grid_x = PAD + LEFT_LABEL_W
    grid_y = PAD + TOP_LABEL_H

    # Month labels: where the month of the week's Sunday changes.
    prev_month = None
    for col, ws in enumerate(week_starts):
        sunday = datetime.fromtimestamp(ws, tz=timezone.utc)
        if sunday.month != prev_month:
            if prev_month is not None or col == 0:
                x = grid_x + col * STEP
                out.append(f'<text x="{x}" y="{PAD + 11}" fill="{text}" {font}>{MONTHS[sunday.month - 1]}</text>')
            prev_month = sunday.month

    for row, label in WEEKDAY_LABELS.items():
        y = grid_y + row * STEP + CELL - 2
        out.append(f'<text x="{PAD}" y="{y}" fill="{text}" {font}>{label}</text>')

    today_utc = today.astimezone(timezone.utc).date()
    for col, ws in enumerate(week_starts):
        sunday = datetime.fromtimestamp(ws, tz=timezone.utc).date()
        for row in range(7):
            day = sunday + timedelta(days=row)
            if day > today_utc:
                continue  # future days stay blank
            n = weeks[ws][row]
            x = grid_x + col * STEP
            y = grid_y + row * STEP
            out.append(
                f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" '
                f'fill="{levels[level_of(n, th)]}" data-date="{day.isoformat()}" data-count="{n}"/>'
            )

    footer_y = grid_y + 7 * STEP + 16
    updated = today.astimezone(JST).strftime("%Y-%m-%d")
    out.append(
        f'<text x="{grid_x}" y="{footer_y}" fill="{text}" {font}>'
        f'{total:,} commits in the last year · {active_repos} active repositories · updated {updated} (JST)</text>'
    )
    legend_x = width - PAD - (5 * STEP) - 46
    out.append(f'<text x="{legend_x - 4}" y="{footer_y}" fill="{text}" {font} text-anchor="end">Less</text>')
    for i, color in enumerate(levels):
        out.append(f'<rect x="{legend_x + i * STEP}" y="{footer_y - 9}" width="{CELL}" height="{CELL}" rx="2" fill="{color}"/>')
    out.append(f'<text x="{legend_x + 5 * STEP + 2}" y="{footer_y}" fill="{text}" {font}>More</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    if not TOKEN:
        raise SystemExit("GITHUB_TOKEN is required")
    repos = list_repos()
    print(f"{len(repos)} repositories in {ORG}")
    weeks, active_repos = aggregate(repos)
    if not weeks:
        raise SystemExit("no commit activity returned; check token permissions")
    now = datetime.now(tz=timezone.utc)
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, theme in THEMES.items():
        path = os.path.join(OUT_DIR, f"activity-{name}.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render(weeks, active_repos, theme, now))
        print(f"wrote {path}")
    total = sum(sum(v) for v in weeks.values())
    print(f"{total} commits across {active_repos} active repositories")


if __name__ == "__main__":
    main()
