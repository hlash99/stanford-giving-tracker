#!/usr/bin/env python3
"""
ANNUAL ID DISCOVERY TOOL  —  run this once when the new event goes live.

Stanford rebuilds the Day of Giving microsite each year, so several IDs baked
into the dashboard change. This script loads the live challenges page in a
headless browser, captures the IDs that actually fire, finds Jen (by name),
and prints a ready-to-paste config block for index.html / notify.py.

WHAT CHANGES YEAR TO YEAR (and what this finds):
  • Leaderboard API URL  -> STANFORD_API  (entity_id + id)   [index.html, notify.py]
  • Jen's ambassador id   -> for sanity-checking the name match
  • Medicine donor feed   -> MEDICINE_SECTION_ID              [index.html, notify.py]

USAGE:
  pip install playwright requests && python -m playwright install chromium
  python discover_ids.py

Best run DURING the live event (the leaderboard widget only fires its API
call when the event is active). Outside the event window it will warn you.
"""

import asyncio
import re
import sys

import requests
from playwright.async_api import async_playwright

CHALLENGES_PAGE = "https://dayofgiving.stanford.edu/pages/challenges-and-leaderboards"
MEDICINE_PAGE   = "https://dayofgiving.stanford.edu/pages/stanford-medicine"
DONORS_TMPL     = "https://dayofgiving.stanford.edu/microsite/api/sections/{}/donors?page=1&limit=3"
TARGET_REGEX    = re.compile(r"varela", re.I)   # Jen — match on last name, case-insensitive


async def discover():
    leaderboard_url = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        def on_request(req):
            nonlocal leaderboard_url
            if "ambassador_leaderboard/?" in req.url and "entity_id=" in req.url:
                leaderboard_url = req.url.split("&t=")[0]  # strip any cache-buster

        page.on("request", on_request)

        print(f"Loading {CHALLENGES_PAGE} ...")
        await page.goto(CHALLENGES_PAGE, timeout=45000, wait_until="networkidle")
        # Scroll to trigger the lazy-loaded leaderboard widget
        for y in range(0, 6000, 700):
            await page.evaluate(f"window.scrollTo(0,{y})")
            await page.wait_for_timeout(700)
        await page.wait_for_timeout(3000)
        await browser.close()

    return leaderboard_url


def find_jen(leaderboard_url):
    r = requests.get(leaderboard_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    parts = [p for p in r.json().get("show_participants", []) if not p.get("hide")]
    parts.sort(key=lambda p: -p["conversion"])
    jen = next((p for p in parts if TARGET_REGEX.search(p["name"])), None)
    return jen, parts


def discover_medicine_section():
    """Find the Stanford Medicine donor-feed section ID and confirm it returns data."""
    html = requests.get(MEDICINE_PAGE, headers={"User-Agent": "Mozilla/5.0"}, timeout=15).text
    ordered = []
    m = re.search(r'"sections":\{"allIds":\[([^\]]*)\]', html)
    if m:
        ordered += re.findall(r"[a-f0-9]{24}", m.group(1))
    for tok in re.findall(r"[a-f0-9]{24}", html):
        if tok not in ordered:
            ordered.append(tok)
    for sid in ordered:
        try:
            j = requests.get(DONORS_TMPL.format(sid),
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=12).json()
            if j.get("donations"):
                return sid
        except Exception:
            continue
    return None


def main():
    leaderboard_url = asyncio.run(discover())

    print("\n" + "=" * 66)
    if not leaderboard_url:
        print("⚠️  Could not capture the ambassador_leaderboard request.")
        print("    The leaderboard widget only fires during the live event.")
        print("    Re-run this DURING the event window, or inspect the page's")
        print("    Network tab for an 'ambassador_leaderboard/?entity_id=...&id=...' call.")
        sys.exit(1)

    print(f"✅ Leaderboard API URL:\n   {leaderboard_url}\n")

    try:
        jen, parts = find_jen(leaderboard_url)
    except Exception as e:
        print(f"⚠️  Captured the URL but couldn't fetch/parse it: {e}")
        sys.exit(1)

    if jen:
        rank = next((i + 1 for i, p in enumerate(parts) if TARGET_REGEX.search(p["name"])), "?")
        print(f"✅ Found Jen: '{jen['name']}'  id_string={jen['id_string']}  "
              f"gifts={jen['conversion']}  rank=#{rank}")
    else:
        print("⚠️  No participant matching /varela/i in the leaderboard!")
        print("    Top participants currently:")
        for p in parts[:6]:
            print(f"      {p['name']}: {p['conversion']}  (id {p['id_string']})")
        print("    Jen may be listed under a different name this year — check the list above.")

    med = discover_medicine_section()
    print(f"\n{'✅' if med else '⚠️ '} Medicine donor-feed section ID: {med or 'NOT FOUND'}")

    # Ready-to-paste config
    print("\n" + "=" * 66)
    print("PASTE INTO index.html AND notify.py:\n")
    print(f'  STANFORD_API        = "{leaderboard_url}"')
    if med:
        print(f'  MEDICINE_SECTION_ID = "{med}"')
    print("\nThen add a YEAR_ARCHIVES entry after the event ends.")
    print("=" * 66)


if __name__ == "__main__":
    main()
