"""
Data Accumulation Health Check — scripts/check_data.py

Standalone diagnostic script to verify the capture pipeline is actually
storing useful data. Run periodically while the daemon is accumulating
data to catch silent failures early.

Usage:
    python scripts/check_data.py
"""

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Resolve paths relative to project root
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DB_PATH = PROJECT_ROOT / "data" / "context.db"


def check_data():
    if not DB_PATH.exists():
        print("❌  Database not found at:", DB_PATH)
        print("   Run 'python main.py --no-audio' first to initialize.")
        return False

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # ─── Basic Counts ────────────────────────────────────────────────
    total = conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
    screen = conn.execute(
        "SELECT COUNT(*) FROM captures WHERE source='screen'"
    ).fetchone()[0]
    audio = conn.execute(
        "SELECT COUNT(*) FROM captures WHERE source='audio'"
    ).fetchone()[0]

    db_size_mb = DB_PATH.stat().st_size / (1024 * 1024)

    print("═" * 55)
    print("  Ambient Context Engine — Data Health Check")
    print("═" * 55)
    print(f"\n  📊 Total captures:   {total}")
    print(f"     Screen:           {screen}")
    print(f"     Audio:            {audio}")
    print(f"     DB size:          {db_size_mb:.2f} MB")

    if total == 0:
        print("\n  ⚠️  No captures found! Pipeline may not be running.")
        conn.close()
        return False

    # ─── Time Range ──────────────────────────────────────────────────
    first = conn.execute("SELECT MIN(timestamp) FROM captures").fetchone()[0]
    last = conn.execute("SELECT MAX(timestamp) FROM captures").fetchone()[0]
    print(f"\n  📅 First capture:    {first}")
    print(f"     Last capture:     {last}")

    try:
        first_dt = datetime.fromisoformat(first)
        last_dt = datetime.fromisoformat(last)
        span = last_dt - first_dt
        print(f"     Data span:        {span}")
    except (ValueError, TypeError):
        pass

    # ─── Recent Activity (last hour) ────────────────────────────────
    one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
    recent_count = conn.execute(
        "SELECT COUNT(*) FROM captures WHERE timestamp > ?",
        (one_hour_ago,),
    ).fetchone()[0]

    print(f"\n  🕐 Captures in last hour: {recent_count}")
    if recent_count == 0:
        print("     ⚠️  No recent captures — pipeline may have stopped!")

    # ─── OCR Text Quality ────────────────────────────────────────────
    avg_len = conn.execute(
        "SELECT AVG(LENGTH(text_content)) FROM captures WHERE source='screen'"
    ).fetchone()[0]

    if avg_len is not None:
        print(f"\n  📝 Avg OCR text length:  {avg_len:.0f} chars")
        if avg_len < 20:
            print("     ⚠️  Very short — OCR may be failing or screens are sparse")
        elif avg_len < 100:
            print("     ⚡ Short-ish — could be normal for simple screens")
        else:
            print("     ✅ Looks reasonable")

    # ─── Recent Window Titles (sample) ───────────────────────────────
    recent_windows = conn.execute(
        """
        SELECT DISTINCT window_title FROM captures
        WHERE source='screen' AND window_title IS NOT NULL
        ORDER BY timestamp DESC
        LIMIT 10
        """
    ).fetchall()

    if recent_windows:
        print(f"\n  🪟 Recent window titles:")
        for row in recent_windows:
            title = row[0]
            if title:
                print(f"     • {title[:70]}")

    # ─── Captures per Hour Distribution ──────────────────────────────
    hourly = conn.execute(
        """
        SELECT
            SUBSTR(timestamp, 1, 13) AS hour,
            COUNT(*) AS cnt
        FROM captures
        GROUP BY hour
        ORDER BY hour DESC
        LIMIT 12
        """
    ).fetchall()

    if hourly:
        print(f"\n  📈 Captures per hour (recent):")
        for row in hourly:
            bar = "█" * min(int(row[1] / 10), 40)
            print(f"     {row[0]}  {row[1]:>4}  {bar}")

    # ─── Dedup Effectiveness ─────────────────────────────────────────
    if screen > 0:
        # Check how many unique OCR texts vs total
        unique_texts = conn.execute(
            "SELECT COUNT(DISTINCT text_content) FROM captures WHERE source='screen'"
        ).fetchone()[0]
        dedup_ratio = unique_texts / screen if screen > 0 else 1.0
        print(f"\n  🔄 Dedup ratio:  {unique_texts}/{screen} unique texts ({dedup_ratio:.0%})")
        if dedup_ratio < 0.3:
            print("     ⚠️  Very low uniqueness — OCR dedup threshold may be too loose")

    print("\n" + "═" * 55)
    conn.close()
    return total > 0


if __name__ == "__main__":
    ok = check_data()
    sys.exit(0 if ok else 1)
