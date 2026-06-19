#!/usr/bin/env python3
"""Publish benchmark results to the public GitHub Pages repo.
Called by the Kobayashi Maru cron loop each wake.
"""
import json, subprocess, sys, os
from datetime import datetime, timezone
from pathlib import Path

RESULTS_REPO = Path("/home/kara/kobayashi-maru-results")
DATA_FILE = RESULTS_REPO / "data" / "leaderboard.json"
AC_FILE = Path("/home/kara/Kobayashi-Maru/.hermes/acceptance-criteria.md")

def parse_latest_wake():
    """Extract wake number, kill rate, and findings from ACs."""
    if not AC_FILE.exists():
        return None
    text = AC_FILE.read_text()
    lines = text.split("\n")
    wake_num = None
    kills = 0
    episodes = 0
    finding = ""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for i, line in enumerate(lines):
        if "Wake" in line and "Results" in line and "UTC" in line:
            parts = line.split()
            for j, p in enumerate(parts):
                if p.startswith("Wake") and j+1 < len(parts):
                    try:
                        wake_num = int(parts[j+1])
                    except ValueError:
                        pass
            # extract date
            for p in parts:
                if "~" in p and "UTC" in p:
                    date_str = p.replace("~", "").replace("UTC", "").strip()[:10]
                    break
        if wake_num and "/" in line and "kills" in line:
            # e.g. "**2/2 kills" or "**1/3 completed"
            import re
            m = re.search(r'(\d+)/(\d+)\s*(kills|completed)', line)
            if m:
                kills = int(m.group(1))
                episodes = int(m.group(2))
        if wake_num and finding == "" and ("Key Observations" in line or "Key Finding" in line):
            # grab next substantive line
            for k in range(i+1, min(i+5, len(lines))):
                if lines[k].strip().startswith("-"):
                    finding = lines[k].strip("- ").strip()[:120]
                    break

    if wake_num is None:
        return None

    return {
        "wake": wake_num,
        "date": date_str,
        "kills": kills,
        "episodes": episodes,
        "killRate": kills / episodes if episodes > 0 else 0,
        "finding": finding,
    }

def update_leaderboard_json(wake_info):
    """Update the leaderboard JSON with latest wake data."""
    data = {}
    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text())

    # Update lastWake
    data["lastWake"] = wake_info

    # Update leaderboard with cumulative stats
    cumulative_kills = sum(r["kills"] for r in data.get("recent", []) if r.get("kills", 0)) + wake_info.get("kills", 0)
    cumulative_episodes = sum(r["episodes"] for r in data.get("recent", []) if r.get("episodes", 0)) + wake_info.get("episodes", 0)

    if data.get("leaderboard") and len(data["leaderboard"]) > 0:
        m = data["leaderboard"][0]
        m["episodes"] = cumulative_episodes
        m["winRate"] = cumulative_kills / cumulative_episodes if cumulative_episodes > 0 else 0

    # Prepend recent
    recent = data.get("recent", [])
    # dedupe by wake number
    recent = [r for r in recent if r.get("wake") != wake_info["wake"]]
    recent.insert(0, wake_info)
    recent = recent[:10]
    data["recent"] = recent

    DATA_FILE.write_text(json.dumps(data, indent=2))
    return data

def push_results(wake_info):
    """Commit and push to public repo."""
    os.chdir(RESULTS_REPO)
    subprocess.run(["git", "pull", "--rebase"], check=False, capture_output=True)
    subprocess.run(["git", "add", "data/leaderboard.json"], check=True)
    subprocess.run(["git", "add", "index.html"], check=True)
    msg = f"results: Wake {wake_info.get('wake', '?')} — {wake_info.get('kills',0)}/{wake_info.get('episodes',0)} kills"
    result = subprocess.run(["git", "commit", "-m", msg], capture_output=True)
    if "nothing to commit" not in result.stdout.decode() and "nothing to commit" not in result.stderr.decode():
        subprocess.run(["git", "push"], check=True, capture_output=True)
        return True
    return False

if __name__ == "__main__":
    wake_info = parse_latest_wake()
    if wake_info is None:
        print("No wake data found in ACs — skipping publish", file=sys.stderr)
        sys.exit(0)

    update_leaderboard_json(wake_info)
    pushed = push_results(wake_info)
    if pushed:
        print(f"Published: Wake {wake_info['wake']} ({wake_info['kills']}/{wake_info['episodes']}) → github.com/totalwindupflightsystems/kobayashi-maru-results")
    else:
        print("No new results to publish (up to date)")
