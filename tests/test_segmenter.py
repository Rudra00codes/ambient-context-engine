"""
Unit tests for Episode Segmentation and Episode Retrieval (Chunk 2)
"""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np

from intelligence.segmenter import build_episodes, ensure_episodes
from storage.db import DatabaseManager


class TestEpisodeSegmenter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(db_path=self.test_db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def _insert_mock_capture(
        self,
        timestamp: str,
        process_name: str,
        window_title: str,
        text_content: str,
        embedding: np.ndarray,
    ) -> int:
        cur = self.db.conn.cursor()
        cur.execute(
            """
            INSERT INTO captures (timestamp, source, text_content, window_title, process_name)
            VALUES (?, 'screen', ?, ?, ?)
            """,
            (timestamp, text_content, window_title, process_name),
        )
        cid = cur.lastrowid
        cur.execute(
            "INSERT INTO vec_captures (rowid, embedding) VALUES (?, ?)",
            (cid, embedding.astype(np.float32).tobytes()),
        )
        self.db.conn.commit()
        return cid

    def test_single_capture_creates_one_episode(self):
        v = np.zeros(384, dtype=np.float32)
        v[0] = 1.0
        self._insert_mock_capture("2026-11-23T10:00:00", "Code.exe", "main.py", "print('hello')", v)

        count = build_episodes(self.db, sim_threshold=0.85, max_gap_secs=120)
        self.assertEqual(count, 1)

        cur = self.db.conn.cursor()
        ep = cur.execute("SELECT * FROM episodes").fetchone()
        self.assertEqual(ep["process_name"], "Code.exe")
        self.assertEqual(ep["dominant_title"], "main.py")
        self.assertEqual(ep["capture_count"], 1)
        self.assertEqual(ep["start_time"], "2026-11-23T10:00:00")
        self.assertEqual(ep["end_time"], "2026-11-23T10:00:00")

    def test_contiguous_similar_captures_join_episode(self):
        # Two captures with identical process and embedding similarity ~1.0, 5s apart
        v1 = np.zeros(384, dtype=np.float32)
        v1[0] = 1.0
        v2 = np.zeros(384, dtype=np.float32)
        v2[0] = 0.99
        v2[1] = 0.05
        v2 /= np.linalg.norm(v2)

        self._insert_mock_capture("2026-11-23T10:00:00", "chrome.exe", "Google Search", "search term", v1)
        self._insert_mock_capture("2026-11-23T10:00:05", "chrome.exe", "Google Search", "search term 2", v2)

        count = build_episodes(self.db, sim_threshold=0.85, max_gap_secs=120)
        self.assertEqual(count, 1)

        cur = self.db.conn.cursor()
        ep = cur.execute("SELECT * FROM episodes").fetchone()
        self.assertEqual(ep["capture_count"], 2)
        self.assertEqual(ep["start_time"], "2026-11-23T10:00:00")
        self.assertEqual(ep["end_time"], "2026-11-23T10:00:05")

        # Check membership table
        members = cur.execute("SELECT capture_id FROM episode_captures WHERE episode_id = ?", (ep["id"],)).fetchall()
        self.assertEqual(len(members), 2)

    def test_window_title_change_alone_does_not_split_episode(self):
        # Key requirement: browser tab title changes should NOT cause over-fragmentation
        v1 = np.zeros(384, dtype=np.float32)
        v1[0] = 1.0
        v2 = np.zeros(384, dtype=np.float32)
        v2[0] = 0.98
        v2[1] = 0.1
        v2 /= np.linalg.norm(v2)

        # Same process chrome.exe, different tab titles, cosine sim > 0.85, gap 10s
        self._insert_mock_capture("2026-11-23T10:00:00", "chrome.exe", "Tab 1 - Google Chrome", "doc content", v1)
        self._insert_mock_capture("2026-11-23T10:00:10", "chrome.exe", "Tab 2 - Google Chrome", "doc content 2", v2)

        count = build_episodes(self.db, sim_threshold=0.85, max_gap_secs=120)
        self.assertEqual(count, 1)

        ep = self.db.conn.execute("SELECT * FROM episodes").fetchone()
        self.assertEqual(ep["capture_count"], 2)
        self.assertEqual(ep["process_name"], "chrome.exe")

    def test_process_change_splits_episode(self):
        v = np.zeros(384, dtype=np.float32)
        v[0] = 1.0

        # Different process names (chrome.exe vs Code.exe)
        self._insert_mock_capture("2026-11-23T10:00:00", "chrome.exe", "Docs", "some text", v)
        self._insert_mock_capture("2026-11-23T10:00:05", "Code.exe", "Docs", "some text", v)

        count = build_episodes(self.db, sim_threshold=0.85, max_gap_secs=120)
        self.assertEqual(count, 2)

    def test_gap_exceeding_max_gap_splits_episode(self):
        v = np.zeros(384, dtype=np.float32)
        v[0] = 1.0

        # Gap is 300 seconds (> max_gap 120s)
        self._insert_mock_capture("2026-11-23T10:00:00", "Code.exe", "editor", "text", v)
        self._insert_mock_capture("2026-11-23T10:05:00", "Code.exe", "editor", "text", v)

        count = build_episodes(self.db, sim_threshold=0.85, max_gap_secs=120)
        self.assertEqual(count, 2)

    def test_low_similarity_splits_episode(self):
        # Orthogonal embeddings (cosine sim = 0.0 < threshold 0.85)
        v1 = np.zeros(384, dtype=np.float32)
        v1[0] = 1.0
        v2 = np.zeros(384, dtype=np.float32)
        v2[1] = 1.0

        self._insert_mock_capture("2026-11-23T10:00:00", "Code.exe", "editor", "python code", v1)
        self._insert_mock_capture("2026-11-23T10:00:05", "Code.exe", "editor", "completely different topic", v2)

        count = build_episodes(self.db, sim_threshold=0.85, max_gap_secs=120)
        self.assertEqual(count, 2)

    def test_dominant_title_and_representative_selection(self):
        v1 = np.zeros(384, dtype=np.float32)
        v1[0] = 1.0
        v2 = np.zeros(384, dtype=np.float32)
        v2[0] = 0.95
        v2[1] = 0.1
        v2 /= np.linalg.norm(v2)
        v3 = np.zeros(384, dtype=np.float32)
        v3[0] = 0.96
        v3[2] = 0.1
        v3 /= np.linalg.norm(v3)

        # 2 captures titled "Title A", 1 titled "Title B" -> Dominant should be "Title A"
        c1 = self._insert_mock_capture("2026-11-23T10:00:00", "app.exe", "Title A", "First text", v1)
        c2 = self._insert_mock_capture("2026-11-23T10:00:05", "app.exe", "Title A", "Second text", v2)
        c3 = self._insert_mock_capture("2026-11-23T10:00:10", "app.exe", "Title B", "Third text", v3)

        count = build_episodes(self.db, sim_threshold=0.80, max_gap_secs=120)
        self.assertEqual(count, 1)

        ep = self.db.conn.execute("SELECT * FROM episodes").fetchone()
        self.assertEqual(ep["dominant_title"], "Title A")
        self.assertEqual(ep["capture_count"], 3)
        self.assertIn(ep["representative_capture_id"], [c1, c2, c3])
        self.assertTrue(len(ep["representative_text"]) > 0)

    def test_ensure_episodes_lazy_build(self):
        v = np.zeros(384, dtype=np.float32)
        v[0] = 1.0
        self._insert_mock_capture("2026-11-23T10:00:00", "app.exe", "title", "text", v)

        # Before ensure_episodes, episodes table is empty
        ep_count_before = self.db.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        self.assertEqual(ep_count_before, 0)

        # ensure_episodes lazily builds them
        count = ensure_episodes(self.db)
        self.assertEqual(count, 1)

        # Second call does not re-build
        count2 = ensure_episodes(self.db)
        self.assertEqual(count2, 1)

    def test_search_episodes_retrieval(self):
        v1 = np.zeros(384, dtype=np.float32)
        v1[0] = 1.0
        v2 = np.zeros(384, dtype=np.float32)
        v2[1] = 1.0

        self._insert_mock_capture("2026-11-23T10:00:00", "code.exe", "requirements.txt", "fastapi uvicorn", v1)
        self._insert_mock_capture("2026-11-23T11:00:00", "chrome.exe", "WhatsApp", "chat messages", v2)

        build_episodes(self.db)

        # Search for "requirements.txt" with time range 09:30 to 10:30
        res = self.db.search_episodes(
            query_embedding=v1,
            query_text="requirements",
            limit=5,
            time_range=("2026-11-23T09:30:00", "2026-11-23T10:30:00"),
        )
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["process_name"], "code.exe")
        self.assertIn("fastapi", res[0]["text_content"])
        self.assertEqual(res[0]["source"], "episode")


if __name__ == "__main__":
    unittest.main()
