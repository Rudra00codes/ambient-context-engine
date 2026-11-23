"""
Intelligence Layer — Episode Segmenter (Chunk 2)

Collapses contiguous near-duplicate captures into cohesive activity episodes.
A capture joins the current episode only if:
1. Temporal gap <= EPISODE_MAX_GAP_SECS (default 120s)
2. Process name is identical
3. Cosine similarity between capture embedding and running centroid >= EPISODE_SIM_THRESHOLD (default 0.85)

Does NOT split on window title changes alone to avoid over-fragmentation from browser tabs.
Maintains a running normalized centroid vector for the active episode.
"""

import logging
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from config import (
    EPISODE_MAX_GAP_SECS,
    EPISODE_REPRESENTATIVE_MAX_CHARS,
    EPISODE_SIM_THRESHOLD,
)
from storage.db import DatabaseManager

logger = logging.getLogger(__name__)


def build_episodes(
    db: DatabaseManager,
    start: Optional[str] = None,
    end: Optional[str] = None,
    sim_threshold: Optional[float] = None,
    max_gap_secs: Optional[int] = None,
    replace_existing: bool = True,
) -> int:
    """
    Segment captures in the specified time range into episodes and store them.

    Args:
        db: DatabaseManager instance.
        start: Optional start timestamp (ISO string).
        end: Optional end timestamp (ISO string).
        sim_threshold: Cosine similarity threshold for joining an episode.
        max_gap_secs: Maximum allowed idle gap in seconds between captures.
        replace_existing: If True, deletes existing episodes overlapping the range.

    Returns:
        Number of episodes created and stored.
    """
    threshold = EPISODE_SIM_THRESHOLD if sim_threshold is None else sim_threshold
    max_gap = EPISODE_MAX_GAP_SECS if max_gap_secs is None else max_gap_secs

    # Query captures ordered chronologically
    query = """
        SELECT c.id, c.timestamp, c.process_name, c.window_title, c.text_content, v.embedding
        FROM captures c
        JOIN vec_captures v ON c.id = v.rowid
        WHERE (? IS NULL OR c.timestamp >= ?)
          AND (? IS NULL OR c.timestamp <= ?)
        ORDER BY c.timestamp ASC, c.id ASC
    """
    params = (start, start, end, end)
    cursor = db.conn.cursor()
    rows = cursor.execute(query, params).fetchall()

    if not rows:
        logger.info("No captures found in range to build episodes.")
        return 0

    logger.info(
        f"Building episodes for {len(rows)} captures (sim_threshold={threshold:.2f}, max_gap={max_gap}s)..."
    )

    raw_episodes: List[Dict[str, Any]] = []
    current_ep: Optional[Dict[str, Any]] = None

    for row in rows:
        cid, ts, proc, title, text, emb_bytes = (
            row["id"],
            row["timestamp"],
            row["process_name"],
            row["window_title"],
            row["text_content"],
            row["embedding"],
        )

        emb = np.frombuffer(emb_bytes, dtype=np.float32)
        norm = np.linalg.norm(emb)
        emb_norm = emb / norm if norm > 0 else emb
        ts_dt = datetime.fromisoformat(ts)

        if current_ep is None:
            # Start initial episode
            current_ep = {
                "proc": proc,
                "captures": [(cid, ts, proc, title, text, emb_norm)],
                "end_dt": ts_dt,
                "sum_vec": emb_norm.copy(),
                "centroid": emb_norm.copy(),
            }
        else:
            gap_secs = (ts_dt - current_ep["end_dt"]).total_seconds()
            sim = float(np.dot(emb_norm, current_ep["centroid"]))
            same_proc = (proc == current_ep["proc"])

            if gap_secs <= max_gap and same_proc and sim >= threshold:
                # Capture joins the current episode
                current_ep["captures"].append((cid, ts, proc, title, text, emb_norm))
                current_ep["end_dt"] = ts_dt
                current_ep["sum_vec"] += emb_norm
                sum_norm = np.linalg.norm(current_ep["sum_vec"])
                current_ep["centroid"] = (
                    current_ep["sum_vec"] / sum_norm if sum_norm > 0 else current_ep["sum_vec"]
                )
            else:
                # Finalize current episode and begin a new one
                raw_episodes.append(current_ep)
                current_ep = {
                    "proc": proc,
                    "captures": [(cid, ts, proc, title, text, emb_norm)],
                    "end_dt": ts_dt,
                    "sum_vec": emb_norm.copy(),
                    "centroid": emb_norm.copy(),
                }

    if current_ep:
        raw_episodes.append(current_ep)

    # Clean existing episodes in range if requested
    if replace_existing:
        try:
            if start is None and end is None:
                db.conn.execute("DELETE FROM episode_captures")
                db.conn.execute("DELETE FROM episodes")
            else:
                # Find overlapping episodes to remove
                del_cur = db.conn.cursor()
                cand_ids = [
                    r[0]
                    for r in del_cur.execute(
                        """
                        SELECT id FROM episodes
                        WHERE (? IS NULL OR end_time >= ?)
                          AND (? IS NULL OR start_time <= ?)
                        """,
                        (start, start, end, end),
                    ).fetchall()
                ]
                if cand_ids:
                    placeholders = ",".join("?" for _ in cand_ids)
                    db.conn.execute(
                        f"DELETE FROM episode_captures WHERE episode_id IN ({placeholders})",
                        cand_ids,
                    )
                    db.conn.execute(
                        f"DELETE FROM episodes WHERE id IN ({placeholders})",
                        cand_ids,
                    )
            db.conn.commit()
        except Exception as e:
            db.conn.rollback()
            logger.warning(f"Error clearing previous episodes: {e}")

    # Prepare structured episode rows
    episodes_to_insert: List[Tuple] = []
    membership_to_insert: List[Tuple[int, int]] = []

    for ep_dict in raw_episodes:
        caps = ep_dict["captures"]
        start_time = caps[0][1]
        end_time = caps[-1][1]
        proc_name = ep_dict["proc"]
        cap_count = len(caps)

        # Dominant window title: most common title among captures
        titles = [c[3] for c in caps if c[3]]
        dominant_title = Counter(titles).most_common(1)[0][0] if titles else proc_name

        # Final normalized centroid
        centroid = ep_dict["centroid"].astype(np.float32)

        # Representative capture: highest cosine similarity to centroid
        best_sim = -2.0
        best_cap = caps[0]
        for c in caps:
            c_norm = c[5]
            sim = float(np.dot(c_norm, centroid))
            if sim > best_sim:
                best_sim = sim
                best_cap = c

        rep_id = best_cap[0]
        rep_text = (best_cap[4] or "")[:EPISODE_REPRESENTATIVE_MAX_CHARS]

        # Insert episode row
        cursor.execute(
            """
            INSERT INTO episodes
                (start_time, end_time, process_name, dominant_title,
                 capture_count, centroid, representative_text, representative_capture_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                start_time,
                end_time,
                proc_name,
                dominant_title,
                cap_count,
                centroid.tobytes(),
                rep_text,
                rep_id,
            ),
        )
        ep_id = cursor.lastrowid

        for c in caps:
            membership_to_insert.append((ep_id, c[0]))

    # Batch insert episode memberships
    cursor.executemany(
        """
        INSERT OR IGNORE INTO episode_captures (episode_id, capture_id)
        VALUES (?, ?)
        """,
        membership_to_insert,
    )

    db.conn.commit()
    logger.info(
        f"Stored {len(raw_episodes)} episodes covering {len(rows)} captures "
        f"(compression ratio: {len(rows)/len(raw_episodes):.2f}x)."
    )
    return len(raw_episodes)


def ensure_episodes(
    db: DatabaseManager,
    start: Optional[str] = None,
    end: Optional[str] = None,
    sim_threshold: Optional[float] = None,
) -> int:
    """
    Ensure that episodes exist in the database for the given range.
    If none exist, builds them automatically.
    """
    cur = db.conn.cursor()
    query = """
        SELECT COUNT(*) FROM episodes
        WHERE (? IS NULL OR end_time >= ?)
          AND (? IS NULL OR start_time <= ?)
    """
    count = cur.execute(query, (start, start, end, end)).fetchone()[0]
    if count == 0:
        logger.info("No episodes found for requested range; triggering build_episodes...")
        return build_episodes(db, start=start, end=end, sim_threshold=sim_threshold)
    return count
