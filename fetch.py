#!/usr/bin/env python3
"""Fetches latest leaderboard and appends a data point to data.json."""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

API_URL     = ("https://dayofgiving.stanford.edu/ambassador_leaderboard/"
               "?entity_id=67217afd5aff7d247806bd0e&id=678773be4cf009577e8c454b&")
HOME_URL    = "https://dayofgiving.stanford.edu/pages/home-2697"
TARGET_NAME  = "Jen Varela"     # display only
TARGET_MATCH = "varela"         # case-insensitive substring match on API name
# Stanford's ambassador id for Jen this year (discover_ids.py prints it). When
# set it wins over the name, which Stanford can change — in Oct 2026 her old
# 465-gift listing was renamed "Joe Getschow". Keep in sync with index.html.
TARGET_ID_STRING = ""
DATA_FILE   = os.path.join(os.path.dirname(__file__), "data.json")

# Browser-like headers — Stanford intermittently 403s plain/datacenter requests.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://dayofgiving.stanford.edu/pages/challenges-and-leaderboards",
}

def robust_get(url, timeout=15, retries=4):
    """GET with browser headers + exponential backoff on transient errors (403/429/5xx)."""
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code in (403, 429) or r.status_code >= 500:
                last = requests.exceptions.HTTPError(f"{r.status_code} for {url}")
                time.sleep(2 ** i)          # 1s, 2s, 4s, 8s
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(2 ** i)
    raise last

def is_target(p):
    if TARGET_ID_STRING and p.get("id_string"):
        return p["id_string"] == TARGET_ID_STRING
    return TARGET_MATCH in (p.get("name") or "").lower()

def fetch_site_totals():
    try:
        html = robust_get(HOME_URL).text
        def grab(key, cast=int):
            m = re.search(rf'"{key}"\s*:\s*([\d.]+)', html)
            return cast(float(m.group(1))) if m else None
        return {
            "site_gifts":  grab("total_family_donations_count"),
            "site_donors": grab("total_family_supporters"),
            "site_raised": grab("amount_raised_including_family", cast=float),
        }
    except Exception as e:
        print(f"[site totals error] {e}", file=sys.stderr)
        return {"site_gifts": None, "site_donors": None, "site_raised": None}

def main():
    try:
        r = robust_get(API_URL)
    except Exception as e:
        # Stanford is briefly blocking us (403/429) or unreachable. This is a
        # best-effort backup poller — a single missed cycle is harmless, the
        # next cron / the local tracker will catch up. Exit cleanly so the
        # workflow doesn't email a failure for a transient block.
        print(f"Leaderboard fetch failed after retries ({e}) — skipping this cycle.", file=sys.stderr)
        sys.exit(0)
    try:
        participants = r.json().get("show_participants") or []
    except Exception as e:
        # A 200 that isn't the leaderboard JSON (block page, maintenance HTML,
        # changed shape). Same policy as a failed fetch: skip, don't fail.
        print(f"::warning::Leaderboard response was not the expected JSON ({e}). Skipping.")
        sys.exit(0)
    # Only rows that carry a numeric gift count can be ranked.
    ranked = sorted([p for p in participants
                     if isinstance(p, dict) and not p.get("hide")
                     and isinstance(p.get("conversion"), (int, float))],
                    key=lambda p: -p["conversion"])

    target = next((p for p in ranked if is_target(p)), None)
    leader = ranked[0] if ranked else None
    second = ranked[1] if len(ranked) > 1 else None

    if not target or not leader:
        # Off-season: Stanford's leaderboard may be empty/archived, or Jen's
        # listing renamed. Exit cleanly (success, no-op) so the scheduled
        # workflow doesn't email a failure — notify.py files an issue if she's
        # missing in the run-up to the event. The ::warning:: line shows up as
        # an annotation on the Actions run.
        print(f"::warning::{TARGET_NAME} or leader not found in Stanford response "
              "(off-season, or her listing changed). Skipping.")
        sys.exit(0)

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            data = json.load(f)
    else:
        data = {"history": []}

    totals = fetch_site_totals()
    def build_point():
        return {
            "ts":           datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "target_gifts": target["conversion"],
            "leader_gifts": leader["conversion"],
            "leader_name":  leader["name"],
            "second_gifts": second["conversion"] if second else None,
            "second_name":  second["name"]       if second else None,
            "delta":        leader["conversion"] - target["conversion"],
            "target_rank":  next((i + 1 for i, p in enumerate(ranked) if is_target(p)), None),
            "site_gifts":   totals["site_gifts"],
            "site_donors":  totals["site_donors"],
            "site_raised":  totals["site_raised"],
        }

    history = data.setdefault("history", [])
    prev_last = history[-1] if history else None   # newest point already on disk
    if history:
        last = history[-1]
        if (last["target_gifts"] == target["conversion"] and
                last["leader_gifts"] == leader["conversion"] and
                last.get("second_gifts") == (second["conversion"] if second else None)):
            print(f"No change — Jen={target['conversion']}, #1={leader['conversion']}, skipping commit")
        else:
            point = build_point()
            data["history"].append(point)
            print(f"Appended: Jen={point['target_gifts']}, "
                  f"#1={point['leader_gifts']}, #2={point['second_gifts']}, gap={point['delta']}")
    else:
        data["history"].append(build_point())

    def money(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    board = [
        {"rank": i + 1, "name": p.get("name") or "", "id_string": p.get("id_string"),
         "gifts": p["conversion"],
         "campaign": p.get("campaign_name") or "",
         "raised": money(p.get("amount_raised"))}
        for i, p in enumerate(ranked[:10])
    ]

    # ── Per-year final board ──────────────────────────────────────────────
    # `leaderboard` is only ever "whatever Stanford showed last", so the first
    # fetch of a new year's microsite used to wipe the previous year's final
    # top 10 (and with it Team Jen's dollars raised, which the page needs for
    # that year's results card and the all-time total). Keep a copy per year.
    finals = data.setdefault("finals", {})
    now_year = str(datetime.now(timezone.utc).year)
    # One-time: file the board already on disk under the year it was recorded.
    if prev_last and data.get("leaderboard"):
        prev_year = str(prev_last.get("ts", ""))[:4]
        if prev_year.isdigit() and prev_year not in finals:
            finals[prev_year] = {"ts": prev_last["ts"],
                                 "target_gifts": prev_last.get("target_gifts"),
                                 "leaderboard": data["leaderboard"]}
    # Refresh this year's copy, but never with a lower count for Jen: gift
    # counts only grow during an event, so a drop means Stanford has reset the
    # board for the next one and the stored copy is the final result to keep.
    kept = finals.get(now_year)
    if not kept or (kept.get("target_gifts") or 0) <= target["conversion"]:
        finals[now_year] = {"ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "target_gifts": target["conversion"],
                            "leaderboard": board}

    data["leaderboard"] = board

    # Write to a temp file and swap it in, so a crash mid-write can never leave
    # a truncated data.json to be committed over the recorded history.
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, DATA_FILE)

    print("data.json updated")

if __name__ == "__main__":
    main()
