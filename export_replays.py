#!/usr/bin/env python3
"""Export episode replay data from benchmark runs to the public GitHub Pages repo.
Scans ~/.kobayashi/data/benchmark_*/episodes/*/replay.jsonl,
converts JSONL → JSON array, copies to data/replays/<episode_id>.json,
generates data/replays-manifest.json.
"""
import json, os, sys
from pathlib import Path
from datetime import datetime, timezone

DATA_ROOT = Path(os.path.expanduser("~/.kobayashi/data"))
PUBLIC_ROOT = Path("/home/kara/kobayashi-maru-results")
REPLAYS_DIR = PUBLIC_ROOT / "data" / "replays"
MANIFEST_FILE = PUBLIC_ROOT / "data" / "replays-manifest.json"

MAX_REPLAYS = 50          # cap to avoid bloating the repo
MAX_FILE_SIZE_MB = 2      # skip replays larger than this

def discover_replays():
    """Walk benchmark dirs and collect all replay.jsonl paths with metadata."""
    replays = []
    for bench_dir in sorted(DATA_ROOT.iterdir()):
        if not bench_dir.is_dir() or not bench_dir.name.startswith("benchmark_"):
            continue
        ep_dir = bench_dir / "episodes"
        if not ep_dir.is_dir():
            continue
        for ep in sorted(ep_dir.iterdir()):
            rp = ep / "replay.jsonl"
            if not rp.exists():
                continue
            size_mb = rp.stat().st_size / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                print(f"  SKIP {ep.name}: {size_mb:.1f}MB > {MAX_FILE_SIZE_MB}MB limit", file=sys.stderr)
                continue
            # Parse header line for metadata
            try:
                header = json.loads(rp.read_text().split("\n")[0])
            except Exception:
                continue
            # Parse terminal line for outcome
            lines = rp.read_text().strip().split("\n")
            terminal = {}
            num_turns = max(0, len(lines) - 2)  # minus header + terminal
            if len(lines) >= 2:
                try:
                    last = json.loads(lines[-1])
                    if last.get("terminal"):
                        terminal = last.get("final_metrics", {})
                        num_turns = max(0, len(lines) - 2)
                except Exception:
                    pass

            replay_meta = {
                "episode_id": header.get("episode_id", ep.name),
                "run_id": header.get("run_id", bench_dir.name),
                "model_id": header.get("model_id", "unknown"),
                "scenario_id": header.get("scenario_id", "unknown"),
                "started_at": header.get("started_at", ""),
                "turns": num_turns,
                "termination": terminal.get("termination_reason", "unknown"),
                "hull_remaining_pct": terminal.get("hull_remaining", 0),
                "size_bytes": rp.stat().st_size,
                "source_path": str(rp),
            }
            replays.append(replay_meta)
    # Sort by started_at desc, then by turns desc
    replays.sort(key=lambda r: (r["started_at"] or "", r["turns"]), reverse=True)
    return replays


def export_replays(replays, dry_run=False):
    """Copy replay JSONL files, convert to JSON array, write manifest."""
    REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    exported = 0

    for r in replays[:MAX_REPLAYS]:
        src = Path(r["source_path"])
        dest = REPLAYS_DIR / f"{r['episode_id']}.json"
        # Convert JSONL → JSON array
        try:
            lines = src.read_text().strip().split("\n")
            data = []
            # Skip header, include turn data + terminal
            for line in lines[1:] if len(lines) > 1 else []:
                data.append(json.loads(line))
        except Exception as e:
            print(f"  ERROR reading {src}: {e}", file=sys.stderr)
            continue

        if not dry_run:
            dest.write_text(json.dumps(data))

        manifest.append({
            "episode_id": r["episode_id"],
            "model_id": r["model_id"],
            "scenario_id": r["scenario_id"],
            "started_at": r["started_at"],
            "turns": r["turns"],
            "termination": r["termination"],
            "hull_remaining_pct": round(r["hull_remaining_pct"], 1),
            "file": f"data/replays/{r['episode_id']}.json",
        })
        exported += 1

    if not dry_run:
        MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))
        print(f"  Wrote {exported} replays → {REPLAYS_DIR}")
        print(f"  Manifest → {MANIFEST_FILE}")

    return exported, manifest


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    replays = discover_replays()
    print(f"Found {len(replays)} replays across models")
    # Show model breakdown
    models = {}
    for r in replays:
        m = r["model_id"]
        models[m] = models.get(m, 0) + 1
    for m, c in sorted(models.items()):
        print(f"  {m}: {c}")
    exported, manifest = export_replays(replays, dry_run=dry)
    if dry:
        print(f"\nWould export {exported} replays (dry run)")
        for r in manifest[:5]:
            print(f"  {r['episode_id']} — {r['model_id']} — {r['turns']} turns — {r['termination']}")
        if len(manifest) > 5:
            print(f"  ... and {len(manifest) - 5} more")
