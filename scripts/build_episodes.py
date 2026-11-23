"""
OmniContext — Batch Episode Builder & Analysis Script (Chunk 2)

Usage:
    python scripts/build_episodes.py
    python scripts/build_episodes.py --sweep
    python scripts/build_episodes.py --compare-old
    python scripts/build_episodes.py --start 2026-11-23T21:40:00 --end 2026-11-23T22:05:00
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    DB_PATH,
    EPISODE_MAX_GAP_SECS,
    EPISODE_SIM_THRESHOLD,
    LOG_LEVEL,
)
from intelligence.segmenter import build_episodes
from storage.db import DatabaseManager

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("build_episodes")


def run_threshold_sweep(db: DatabaseManager, start: str = None, end: str = None):
    """Run similarity threshold sweep over 0.80 - 0.95 and print comparison table."""
    thresholds = [0.80, 0.85, 0.90, 0.95]
    print("\n" + "=" * 70)
    print("  OmniContext: Episode Segmentation Threshold Sweep (Chunk 2)")
    print("=" * 70)

    cur = db.conn.cursor()
    total_caps = cur.execute(
        """
        SELECT COUNT(*) FROM captures
        WHERE (? IS NULL OR timestamp >= ?)
          AND (? IS NULL OR timestamp <= ?)
        """,
        (start, start, end, end),
    ).fetchone()[0]

    print(f"Total Captures in Range: {total_caps}")
    print(f"Time Range: {start or 'Earliest'} -> {end or 'Latest'}\n")
    print(f"| {'Threshold':^11} | {'Episodes':^10} | {'Compression Ratio':^19} | {'Avg Captures/Ep':^17} |")
    print(f"|{'-'*13}|{'-'*12}|{'-'*21}|{'-'*19}|")

    results = []
    for th in thresholds:
        # Build without committing permanently during sweep or using transaction rollback
        count = build_episodes(db, start=start, end=end, sim_threshold=th, replace_existing=True)
        compression = total_caps / count if count > 0 else 0.0
        avg_caps = total_caps / count if count > 0 else 0.0
        print(f"| {th:^11.2f} | {count:^10} | {f'{compression:.2f}x':^19} | {f'{avg_caps:.1f}':^17} |")
        results.append((th, count, compression))

    # Re-build with selected default threshold
    build_episodes(db, start=start, end=end, sim_threshold=EPISODE_SIM_THRESHOLD, replace_existing=True)
    print("=" * 70 + "\n")
    return results


def run_compare_old(db: DatabaseManager, start: str = None, end: str = None):
    """Compare new episode segmentation vs old title-change SessionDetector rule."""
    print("\n" + "=" * 70)
    print("  OmniContext: Episode Segmentation vs Old Title-Change Rule")
    print("=" * 70)

    cur = db.conn.cursor()
    caps = cur.execute(
        """
        SELECT id, timestamp, process_name, window_title
        FROM captures
        WHERE (? IS NULL OR timestamp >= ?)
          AND (? IS NULL OR timestamp <= ?)
        ORDER BY timestamp ASC
        """,
        (start, start, end, end),
    ).fetchall()

    if not caps:
        print("No captures in range.")
        return

    total_caps = len(caps)

    # 1. Old Rule: split on window_title change or gap > 5 mins
    old_sessions = 0
    prev_title = None
    prev_ts = None
    for c in caps:
        gap_mins = 0.0
        if prev_ts:
            gap_mins = (datetime.fromisoformat(c["timestamp"]) - datetime.fromisoformat(prev_ts)).total_seconds() / 60.0
        if c["window_title"] != prev_title or gap_mins > 5.0:
            old_sessions += 1
            prev_title = c["window_title"]
        prev_ts = c["timestamp"]

    # 2. New Rule: build_episodes with EPISODE_SIM_THRESHOLD
    new_episodes = build_episodes(db, start=start, end=end, sim_threshold=EPISODE_SIM_THRESHOLD, replace_existing=True)

    old_comp = total_caps / old_sessions if old_sessions > 0 else 0.0
    new_comp = total_caps / new_episodes if new_episodes > 0 else 0.0

    print(f"Total Captures Analyzed: {total_caps}")
    print(f"Time Range: {start or caps[0]['timestamp']} -> {end or caps[-1]['timestamp']}\n")
    print(f"| {'Segmentation Approach':<30} | {'Count':^8} | {'Compression':^13} | {'Avg Duration':^14} |")
    print(f"|{'-'*32}|{'-'*10}|{'-'*15}|{'-'*16}|")
    
    total_span_secs = (datetime.fromisoformat(caps[-1]["timestamp"]) - datetime.fromisoformat(caps[0]["timestamp"])).total_seconds()
    old_dur = total_span_secs / old_sessions if old_sessions > 0 else 0.0
    new_dur = total_span_secs / new_episodes if new_episodes > 0 else 0.0

    print(f"| {'Old Rule (Title-Change)':<30} | {old_sessions:^8} | {f'{old_comp:.2f}x':^13} | {f'{old_dur:.1f}s':^14} |")
    print(f"| {'New Rule (Semantic Episode)':<30} | {new_episodes:^8} | {f'{new_comp:.2f}x':^13} | {f'{new_dur:.1f}s':^14} |")
    print("=" * 70)
    print(f"Fragmentation reduction: {(1.0 - new_episodes / old_sessions) * 100:.1f}% fewer partitions.\n")


def main():
    parser = argparse.ArgumentParser(description="OmniContext Batch Episode Segmenter")
    parser.add_argument("--start", type=str, default=None, help="Start ISO timestamp")
    parser.add_argument("--end", type=str, default=None, help="End ISO timestamp")
    parser.add_argument("--threshold", type=float, default=EPISODE_SIM_THRESHOLD, help="Cosine similarity threshold")
    parser.add_argument("--max-gap", type=int, default=EPISODE_MAX_GAP_SECS, help="Max idle gap in seconds")
    parser.add_argument("--sweep", action="store_true", help="Run threshold sweep (0.80 - 0.95)")
    parser.add_argument("--compare-old", action="store_true", help="Compare vs old SessionDetector rule")

    args = parser.parse_args()

    db = DatabaseManager()

    if args.sweep:
        run_threshold_sweep(db, start=args.start, end=args.end)
    elif args.compare_old:
        run_compare_old(db, start=args.start, end=args.end)
    else:
        created = build_episodes(
            db,
            start=args.start,
            end=args.end,
            sim_threshold=args.threshold,
            max_gap_secs=args.max_gap,
            replace_existing=True,
        )
        print(f"Successfully created and stored {created} episodes.")


if __name__ == "__main__":
    main()
