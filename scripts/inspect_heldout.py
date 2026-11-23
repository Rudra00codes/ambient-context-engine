#!/usr/bin/env python3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import DatabaseManager

db = DatabaseManager()
cur = db.conn.cursor()

print("--- Activity distribution for 2026-11-24 ---")
rows = cur.execute("""
    SELECT process_name, window_title, count(id), min(timestamp), max(timestamp), min(id), max(id)
    FROM captures
    WHERE timestamp >= '2026-11-24'
    GROUP BY process_name, window_title
    ORDER BY count(id) DESC
    LIMIT 20
""").fetchall()

for r in rows:
    print(f"[{r[0]}] '{r[1]}' | count: {r[2]} | {r[3][:19]} -> {r[4][:19]} | ids: {r[5]}-{r[6]}")

db.close()
