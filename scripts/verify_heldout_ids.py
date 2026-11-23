#!/usr/bin/env python3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import DatabaseManager

db = DatabaseManager()
cur = db.conn.cursor()

def check(query_name, sql, params):
    rows = cur.execute(sql, params).fetchall()
    ids = [r[0] for r in rows]
    print(f"[{query_name}] Count: {len(ids)} | First 10 IDs: {ids[:10]}")
    return ids

print("=== Verifying Held-Out Capture IDs ===")
check("HT1 (Arduino 2:20-2:40)", "SELECT id FROM captures WHERE timestamp BETWEEN '2026-11-24T02:20:00' AND '2026-11-24T02:40:00' AND process_name LIKE '%arduino%'", ())
check("HT2 (Apps 3:10-3:20)", "SELECT id FROM captures WHERE timestamp BETWEEN '2026-11-24T03:10:00' AND '2026-11-24T03:20:00'", ())
check("HT3 (Earliest 2026-11-24)", "SELECT id FROM captures WHERE timestamp >= '2026-11-24T00:00:00' ORDER BY timestamp ASC LIMIT 5", ())
check("HS1 (esp32_cam_streamer)", "SELECT id FROM captures WHERE window_title LIKE '%esp32_cam_streamer%' OR text_content LIKE '%esp32_cam_streamer%'", ())
check("HS2 (Monkeytype)", "SELECT id FROM captures WHERE window_title LIKE '%Monkeytype%' OR text_content LIKE '%Monkeytype%'", ())
check("HS3 (Pinterest)", "SELECT id FROM captures WHERE window_title LIKE '%Pinterest%' OR text_content LIKE '%Pinterest%'", ())
check("HH1 (AeroStreamID 2:15-2:45)", "SELECT id FROM captures WHERE timestamp BETWEEN '2026-11-24T02:15:00' AND '2026-11-24T02:45:00' AND (process_name LIKE '%WindowsTerminal%' OR window_title LIKE '%AeroStream%')", ())
check("HH2 (Chunk4.md 3:40-3:45)", "SELECT id FROM captures WHERE timestamp BETWEEN '2026-11-24T03:40:00' AND '2026-11-24T03:45:00' AND window_title LIKE '%Chunk4%'", ())

db.close()
