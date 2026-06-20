#!/usr/bin/env python3
"""Publish benchmark results to the public GitHub Pages repo.
Called by the Kobayashi Maru cron loop each wake.
Now supports multi-scenario breakdowns — parses per-scenario data from ACs.
"""
import json, subprocess, sys, os, re
from datetime import datetime, timezone
from pathlib import Path

RESULTS_REPO = Path("/home/kara/kobayashi-maru-results")
DATA_FILE = RESULTS_REPO / "data" / "leaderboard.json"
AC_FILE = Path("/home/kara/Kobayashi-Maru/.hermes/acceptance-criteria.md")

def parse_cumulative_from_acs():
    """Extract cumulative stats from ACs. Returns (kills, episodes) tuple or None."""
    if not AC_FILE.exists():
        return None
    for line in AC_FILE.read_text().split("\n"):
        m = re.search(r'Cumulative.*?(\d+)/(\d+)', line)
        if m:
            return (int(m.group(1)), int(m.group(2)))
    return None

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
    scenario = "basic_combat"  # default
    
    for i, line in enumerate(lines):
        # Match: "## Latest Wake Results (Wake 52 — June 16 ~05:10 UTC)"
        m = re.search(r'Latest Wake Results.*Wake\s+(\d+)', line, re.IGNORECASE)
        if m:
            wake_num = int(m.group(1))
            date_m = re.search(r'(\d{4}-\d{2}-\d{2}|\w+\s+\d{2})\s*[~]', line)
            if date_m:
                date_str = date_m.group(1)
            # Look for scenario name in the wake header or nearby
            sm = re.search(r'Suite.*?(\w[\w_]+)', line)
            if sm:
                scenario = sm.group(1)
            continue
        
        if wake_num is None:
            continue
            
        km = re.search(r'\*\*.*?(\d+)/(\d+)\s*(?:KILLS|kills|completed)', line, re.IGNORECASE)
        if km and kills == 0:
            kills = int(km.group(1))
            episodes = int(km.group(2))
            finding = line.strip("* ")[:120]
            break
        
        # Per-scenario wake: "## Wake 56 — gauntlet (2/3 kills)"
        sm = re.search(r'Wake\s+\d+\s*[—-]\s*(\w[\w_]*)\s*\((\d+)/(\d+)', line)
        if sm:
            scenario = sm.group(1)
            kills = int(sm.group(2))
            episodes = int(sm.group(3))
            finding = line.strip("# ")[:120]
            break
    
    if wake_num is None:
        return None
    
    return {
        "wake": wake_num,
        "date": date_str,
        "kills": kills if kills > 0 else 0,
        "episodes": episodes if episodes > 0 else 3,
        "killRate": kills / episodes if episodes > 0 else 0,
        "scenario": scenario,
        "finding": finding[:120] if finding else "",
    }

def parse_scenario_breakdown():
    """Parse per-scenario stats from ACs for multi-scenario leaderboard.
    Returns list of {scenario, kills, episodes, killRate} or empty."""
    if not AC_FILE.exists():
        return []
    text = AC_FILE.read_text()
    scenarios = []
    # Look for scenario-specific wake results
    # Pattern: "## Wake N — <scenario> (<kills>/<episodes> kills)"
    for m in re.finditer(r'Wake\s+\d+\s*[—-]\s*(\w[\w_]*)\s*\((\d+)/(\d+)', text):
        name = m.group(1)
        kills = int(m.group(2))
        episodes = int(m.group(3))
        # Avoid duplicate scenarios (take latest)
        if not any(s['scenario'] == name for s in scenarios):
            scenarios.append({
                "scenario": name,
                "kills": kills,
                "episodes": episodes,
                "killRate": kills / episodes if episodes > 0 else 0,
            })
    return scenarios

def update_leaderboard_json(wake_info):
    """Update the leaderboard JSON with latest wake data + per-scenario breakdown."""
    data = {}
    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text())

    data["lastWake"] = wake_info

    cumulative = parse_cumulative_from_acs()
    cumulative_kills = cumulative[0] if cumulative else wake_info.get("kills", 0)
    cumulative_episodes = cumulative[1] if cumulative else wake_info.get("episodes", 3)

    # Update top model stats
    if data.get("leaderboard") and len(data["leaderboard"]) > 0:
        m = data["leaderboard"][0]
        m["episodes"] = cumulative_episodes
        m["winRate"] = cumulative_kills / cumulative_episodes if cumulative_episodes > 0 else 0

    # Recent wakes (deduped by wake number)
    recent = data.get("recent", [])
    recent = [r for r in recent if r.get("wake") != wake_info["wake"]]
    recent.insert(0, wake_info)
    data["recent"] = recent[:10]

    # Per-scenario breakdown
    scenario_data = parse_scenario_breakdown()
    if scenario_data:
        # Merge with existing per-scenario data
        existing_by_name = {s['scenario']: s for s in data.get("scenarios", [])}
        for s in scenario_data:
            existing_by_name[s['scenario']] = s
        data["scenarios"] = list(existing_by_name.values())

    DATA_FILE.write_text(json.dumps(data, indent=2))
    return data

def push_results(wake_info):
    """Commit and push to public repo."""
    os.chdir(RESULTS_REPO)
    subprocess.run(["git", "config", "user.email", "totalwindupflightsystems@users.noreply.github.com"], check=False)
    subprocess.run(["git", "config", "user.name", "totalwindupflightsystems"], check=False)
    subprocess.run(["git", "pull", "--rebase"], check=False, capture_output=True)
    subprocess.run(["git", "add", "data/leaderboard.json"], check=True)
    subprocess.run(["git", "add", "index.html"], check=True)
    subprocess.run(["git", "add", "replay.html"], check=True)
    subprocess.run(["git", "add", "data/replays-manifest.json"], check=True)
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
