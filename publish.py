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

def parse_cumulative_from_acs():
    """Extract cumulative stats from first Cumulative line in ACs.
    Returns (kills, episodes) tuple or None."""
    if not AC_FILE.exists():
        return None
    import re
    for line in AC_FILE.read_text().split("\n"):
        m = re.search(r'Cumulative.*?(\d+)/(\d+)', line)
        if m:
            return (int(m.group(1)), int(m.group(2)))
    return None

def parse_latest_wake():
    """Extract wake number, kill rate, and findings from ACs.
    
    The ACs have sections like:
    ## Latest Wake Results (Wake 52 — June 16 ~05:10 UTC)
    **⚠️ 2/3 KILLS — EP1 FAILED...**
    Cumulative: 330/396 = 83.3%
    """
    if not AC_FILE.exists():
        return None
    text = AC_FILE.read_text()
    lines = text.split("\n")
    
    import re
    wake_num = None
    kills = 0
    episodes = 0
    finding = ""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    for i, line in enumerate(lines):
        # Match section header: "## Latest Wake Results (Wake 52 — June 16 ~05:10 UTC)"
        m = re.search(r'Latest Wake Results.*Wake\s+(\d+)', line, re.IGNORECASE)
        if m:
            wake_num = int(m.group(1))
            # Try to extract date
            date_m = re.search(r'(\d{4}-\d{2}-\d{2}|\w+\s+\d{2})\s*[~]', line)
            if date_m:
                date_str = date_m.group(1)
            continue
        
        if wake_num is None:
            continue
            
        # Match kill count: **⚠️ 2/3 KILLS** or **2/3 kills** or **2/3 KILLS**
        km = re.search(r'\*\*.*?(\d+)/(\d+)\s*(?:KILLS|kills|completed)', line, re.IGNORECASE)
        if km and kills == 0:
            kills = int(km.group(1))
            episodes = int(km.group(2))
            # The rest of the bold line is the finding summary
            finding = line.strip("* ")[:120]
            break  # Got what we need from first match
        
        # Also check for Cumulative line
        cm = re.search(r'Cumulative.*?(\d+)/(\d+)', line)
        if cm and episodes == 0:
            # Use cumulative as fallback
            pass
    
    if wake_num is None:
        return None
    
    return {
        "wake": wake_num,
        "date": date_str,
        "kills": kills if kills > 0 else 0,
        "episodes": episodes if episodes > 0 else 3,
        "killRate": kills / episodes if episodes > 0 else 0,
        "finding": finding[:120] if finding else "",
    }

def update_leaderboard_json(wake_info):
    """Update the leaderboard JSON with latest wake data."""
    data = {}
    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text())

    # Update lastWake
    data["lastWake"] = wake_info

    # Parse cumulative stats from ACs (e.g. "Cumulative: 335/402 = 83.3%")
    cumulative_kills = wake_info.get("kills", 0)
    cumulative_episodes = wake_info.get("episodes", 3)
    cumulative_line = parse_cumulative_from_acs()
    if cumulative_line:
        cumulative_kills = cumulative_line[0]
        cumulative_episodes = cumulative_line[1]

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
    # Ensure git identity is configured for this repo
    subprocess.run(["git", "config", "user.email", "totalwindupflightsystems@users.noreply.github.com"], check=False)
    subprocess.run(["git", "config", "user.name", "totalwindupflightsystems"], check=False)
    subprocess.run(["git", "pull", "--rebase"], check=False, capture_output=True)
    subprocess.run(["git", "add", "data/leaderboard.json"], check=True)
    subprocess.run(["git", "add", "index.html"], check=True)
    subprocess.run(["git", "add", "replay.html"], check=True)
    subprocess.run(["git", "add", "data/replays-manifest.json"], check=True)
    # Add new replay files (but not all 60 every time — git tracks changes)
    replays_dir = RESULTS_REPO / "data" / "replays"
    if replays_dir.exists():
        subprocess.run(["git", "add", str(replays_dir)], check=True)
    msg = f"results: Wake {wake_info.get('wake', '?')} — {wake_info.get('kills',0)}/{wake_info.get('episodes',0)} kills"
    result = subprocess.run(["git", "commit", "-m", msg], capture_output=True)
    if "nothing to commit" not in result.stdout.decode() and "nothing to commit" not in result.stderr.decode():
        subprocess.run(["git", "push"], check=True, capture_output=True)
        return True
    return False

if __name__ == "__main__":
    # First, export fresh replay data
    print("Exporting replay data…", file=sys.stderr)
    export_script = RESULTS_REPO / "export_replays.py"
    if export_script.exists():
        subprocess.run([sys.executable, str(export_script)], check=False)
    
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
