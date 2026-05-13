#!/usr/bin/env python3
"""Fetches latest leaderboard and appends a data point to data.json."""

import json
import os
import sys
from datetime import datetime, timezone

import requests

API_URL     = ("https://dayofgiving.stanford.edu/ambassador_leaderboard/"
               "?entity_id=67217afd5aff7d247806bd0e&id=678773be4cf009577e8c454b&")
TARGET_NAME = "Jen Varela"
DATA_FILE   = os.path.join(os.path.dirname(__file__), "data.json")

def main():
    r = requests.get(API_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    participants = r.json().get("show_participants", [])
    ranked = sorted([p for p in participants if not p.get("hide")],
                    key=lambda p: -p["conversion"])

    target = next((p for p in ranked if p["name"] == TARGET_NAME), None)
    leader = ranked[0] if ranked else None

    if not target or not leader:
        print("Target or leader not found", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            data = json.load(f)
    else:
        data = {"history": []}

    # Deduplicate: skip if counts unchanged since last point
    history = data.get("history", [])
    if history:
        last = history[-1]
        if (last["target_gifts"] == target["conversion"] and
                last["leader_gifts"] == leader["conversion"]):
            print(f"No change — Jen={target['conversion']}, #1={leader['conversion']}, skipping commit")
            # Still update leaderboard snapshot for rank changes below top 2
        else:
            point = {
                "ts":           datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "target_gifts": target["conversion"],
                "leader_gifts": leader["conversion"],
                "leader_name":  leader["name"],
                "delta":        leader["conversion"] - target["conversion"],
                "target_rank":  next(
                    (i + 1 for i, p in enumerate(ranked) if p["name"] == TARGET_NAME), None
                ),
            }
            data["history"].append(point)
            print(f"Appended: Jen={point['target_gifts']}, "
                  f"#1={point['leader_gifts']}, gap={point['delta']}")
    else:
        point = {
            "ts":           datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "target_gifts": target["conversion"],
            "leader_gifts": leader["conversion"],
            "leader_name":  leader["name"],
            "delta":        leader["conversion"] - target["conversion"],
            "target_rank":  next(
                (i + 1 for i, p in enumerate(ranked) if p["name"] == TARGET_NAME), None
            ),
        }
        data["history"].append(point)

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
