#!/usr/bin/env python3
"""Fetches latest leaderboard and appends a data point to data.json."""

import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

API_URL     = ("https://dayofgiving.stanford.edu/ambassador_leaderboard/"
               "?entity_id=67217afd5aff7d247806bd0e&id=678773be4cf009577e8c454b&")
HOME_URL    = "https://dayofgiving.stanford.edu/pages/home-2697"
TARGET_NAME  = "Jen Varela"     # display only
TARGET_MATCH = "varela"         # case-insensitive substring match on API name
DATA_FILE   = os.path.join(os.path.dirname(__file__), "data.json")

def fetch_site_totals():
    try:
        html = requests.get(HOME_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15).text
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
    r = requests.get(API_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    participants = r.json().get("show_participants", [])
    ranked = sorted([p for p in participants if not p.get("hide")],
                    key=lambda p: -p["conversion"])

    target = next((p for p in ranked if TARGET_MATCH in p["name"].lower()), None)
    leader = ranked[0] if ranked else None
    second = ranked[1] if len(ranked) > 1 else None

    if not target or not leader:
        print("Target or leader not found", file=sys.stderr)
        sys.exit(1)

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
            "target_rank":  next(
                (i + 1 for i, p in enumerate(ranked) if TARGET_MATCH in p["name"].lower()), None
            ),
            "site_gifts":   totals["site_gifts"],
            "site_donors":  totals["site_donors"],
            "site_raised":  totals["site_raised"],
        }

    history = data.get("history", [])
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

    data["leaderboard"] = [
        {"rank": i + 1, "name": p["name"],
         "gifts": p["conversion"],
         "campaign": p["campaign_name"],
         "raised": float(p["amount_raised"])}
        for i, p in enumerate(ranked[:10])
    ]

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, separators=(",", ":"))

    print("data.json updated")

if __name__ == "__main__":
    main()
