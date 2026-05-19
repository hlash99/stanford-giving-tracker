#!/usr/bin/env python3
"""
Daily notification checks. Opens a GitHub issue (which emails the repo owner
via GitHub notifications) when:

  1) Stanford publishes the official tie (Jen and Drew at matching gift counts).
  2) We are 3–5 days away from the next Day of Giving event.

Run from GitHub Actions with GITHUB_TOKEN; uses the `gh` CLI for issue ops.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

REPO    = os.environ.get('GH_REPO', 'hlash99/stanford-giving-tracker')
API_URL = ("https://dayofgiving.stanford.edu/ambassador_leaderboard/"
           "?entity_id=67217afd5aff7d247806bd0e&id=678773be4cf009577e8c454b&")

# ──────────────────────────────────────────────────────────────────────
def event_window(year):
    """2nd Wednesday of May, 5am PT → Thursday 5pm PT (PDT = UTC-7)."""
    may1_dow   = datetime(year, 5, 1).weekday()       # Mon=0..Sun=6
    wed_offset = (2 - may1_dow + 7) % 7               # Wed=2 in py weekday
    wed_date   = 1 + wed_offset + 7
    start = datetime(year, 5, wed_date,     12, 0, 0, tzinfo=timezone.utc)  # 5am PT
    end   = datetime(year, 5, wed_date + 2,  0, 0, 0, tzinfo=timezone.utc)
    return start, end

def issue_exists(title_substring):
    """Return True if an open or closed issue contains the given title substring."""
    try:
        r = subprocess.run(
            ['gh', 'issue', 'list', '--repo', REPO, '--state', 'all',
             '--limit', '200', '--json', 'title'],
            capture_output=True, text=True, check=True
        )
        for issue in json.loads(r.stdout or '[]'):
            if title_substring in issue.get('title', ''):
                return True
        return False
    except Exception as e:
        print(f"[issue_exists error] {e}", file=sys.stderr)
        return False

def create_issue(title, body, labels=None):
    cmd = ['gh', 'issue', 'create', '--repo', REPO, '--title', title, '--body', body]
    if labels:
        cmd += ['--label', ','.join(labels)]
    try:
        subprocess.run(cmd, check=True)
        print(f"[issue created] {title}")
    except Exception as e:
        print(f"[create_issue error] {e}", file=sys.stderr)

# ──────────────────────────────────────────────────────────────────────
def check_tie_published():
    """If Jen and Drew now have matching gift counts in Stanford's API, notify."""
    try:
        r = requests.get(API_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        ranked = sorted(
            [p for p in r.json().get('show_participants', []) if not p.get('hide')],
            key=lambda p: -p['conversion']
        )
    except Exception as e:
        print(f"[tie check fetch error] {e}", file=sys.stderr)
        return

    jen  = next((p for p in ranked if 'varela'   in p['name'].lower()), None)
    drew = next((p for p in ranked if 'hutchins' in p['name'].lower()), None)
    if not (jen and drew):
        print("Tie check: Jen or Drew not in current top participants — skipping")
        return
    if jen['conversion'] != drew['conversion']:
        print(f"Tie check: counts differ (Jen={jen['conversion']}, Drew={drew['conversion']}) — no notification")
        return

    if issue_exists("Stanford published the tie"):
        print("Tie already notified — skipping")
        return

    n = jen['conversion']
    create_issue(
        f"Stanford published the tie! Both at {n} gifts",
        f"""## 🏆 Stanford has officially updated their leaderboard to reflect the tie

Both **Jen Varela** and **Drew Hutchins** now show **{n} gifts** in Stanford's public API.

The dashboard at <https://hlash99.github.io/stanford-giving-tracker/> will auto-update to these numbers on the next page refresh (the auto-detection logic we built picks up matching counts and overrides the hardcoded archive values).

- Stanford leaderboard: <https://dayofgiving.stanford.edu/pages/challenges-and-leaderboards>
- Stanford Medicine page: <https://dayofgiving.stanford.edu/pages/stanford-medicine>

*This is an automated notification from the `notify.yml` workflow.*
""",
        labels=["notification"]
    )

def check_upcoming_event():
    """If we're 3–5 days away from the next event start, notify."""
    now  = datetime.now(timezone.utc)
    year = now.year
    start, end = event_window(year)
    if now >= end:
        start, end = event_window(year + 1)

    days_until = (start - now).total_seconds() / 86400
    if not (3.0 <= days_until <= 5.0):
        print(f"Upcoming check: {days_until:.1f} days out (need 3–5) — no notification")
        return

    key = f"Day of Giving {start.year} starts"
    if issue_exists(key):
        print(f"Upcoming event for {start.year} already notified — skipping")
        return

    create_issue(
        f"{key} in ~{int(round(days_until))} days! ({start.strftime('%a %b %d')})",
        f"""## 📅 Stanford Day of Giving {start.year} is almost here!

**Starts:** {start.strftime('%A, %B %d, %Y')} at **5:00 AM Pacific Time**
**Ends:** {(start + timedelta(hours=36)).strftime('%A, %B %d')} at 5:00 PM PT
**Duration:** 36 hours
**Time from now:** ~{days_until:.1f} days

The tracker at <https://hlash99.github.io/stanford-giving-tracker/> will automatically switch into live mode the moment the event opens.

Get ready to rally Team Jen! 💙

- Stanford Day of Giving: <https://dayofgiving.stanford.edu/>

*This is an automated notification from the `notify.yml` workflow.*
""",
        labels=["notification"]
    )

# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    check_tie_published()
    check_upcoming_event()
