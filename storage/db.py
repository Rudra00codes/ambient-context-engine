"""
Storage Layer — Database Manager

Handles all SQLite operations: connection management, schema initialization,
insert/search/cleanup operations. Integrates FTS5 (keyword search) and
sqlite-vec (semantic vector search) with hybrid Reciprocal Rank Fusion.
"""

import sqlite3
import logging
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List

import numpy as np

import sqlite_vec
from config import (
    DB_PATH, EMBEDDING_DIM, SEARCH_TOP_K, RRF_K, RETENTION_DAYS
)

logger = logging.getLogger(__name__)

ENGLISH_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't",
    "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves"
}


def _fts_query(text: str) -> Optional[str]:
    """
    Format a natural-language text string into a valid FTS5 query:
    tokenize to alphanumerics, drop stopwords, quote each term, join with OR.
    Returns None if no terms remain.
    """
    if not text:
        return None
    tokens = re.findall(r"\w+", text.lower())
    content_terms = [t for t in tokens if t not in ENGLISH_STOPWORDS and len(t) > 1]
    if not content_terms:
        return None
    seen = set()
    unique_terms = []
    for t in content_terms:
        if t not in seen:
            seen.add(t)
            unique_terms.append(t)
    return " OR ".join(f'"{t}"' for t in unique_terms)


class DatabaseManager:
    """Thread-safe SQLite database manager with FTS5 + sqlite-vec support."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = self._connect()
        self._init_schema()
        logger.info(f"Database initialized at {self.db_path}")

    def _connect(self) -> sqlite3.Connection:
        """Create a connection with WAL mode and sqlite-vec loaded."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row

        # Enable WAL mode for concurrent reads/writes
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache

        # Load sqlite-vec extension
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        logger.debug("sqlite-vec extension loaded successfully")
        return conn

    def _init_schema(self):
        """Run schema.sql to create tables if they don't exist."""
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, "r") as f:
            schema_sql = f.read()

        try:
            self.conn.executescript(schema_sql)
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize schema: {e}")
            self.conn.rollback()
            raise

    # ─── Insert Operations ───────────────────────────────────────────

    def insert_capture(
        self,
        source: str,
        text_content: str,
        embedding: np.ndarray,
        window_title: Optional[str] = None,
        process_name: Optional[str] = None,
        confidence: Optional[float] = None,
        duration_secs: Optional[float] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        """
        Insert a capture event into all three stores (captures, FTS, vec)
        in a single transaction. Returns the inserted row ID.
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        if embedding.shape != (EMBEDDING_DIM,):
            raise ValueError(
                f"Embedding dimension mismatch: expected {EMBEDDING_DIM}, "
                f"got {embedding.shape}"
            )

        try:
            cursor = self.conn.execute(
                """
                INSERT INTO captures
                    (timestamp, source, text_content, window_title,
                     process_name, confidence, duration_secs)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (timestamp, source, text_content, window_title,
                 process_name, confidence, duration_secs),
            )
            row_id = cursor.lastrowid

            # Insert embedding into vec_captures (rowid must match captures.id)
            embedding_bytes = embedding.astype(np.float32).tobytes()
            self.conn.execute(
                "INSERT INTO vec_captures(rowid, embedding) VALUES (?, ?)",
                (row_id, embedding_bytes),
            )

            self.conn.commit()
            logger.debug(
                f"Inserted capture id={row_id} source={source} "
                f"text_len={len(text_content)}"
            )
            return row_id

        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to insert capture: {e}")
            raise

    def insert_edge(self, source_id: int, target_id: int, relation_type: str):
        """Insert a relationship between two captures in the context graph."""
        try:
            self.conn.execute(
                "INSERT OR IGNORE INTO graph_edges (source_id, target_id, relation_type) VALUES (?, ?, ?)",
                (source_id, target_id, relation_type)
            )
            self.conn.commit()
            logger.debug(f"Inserted graph edge: {source_id} -> {target_id} ({relation_type})")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to insert graph edge: {e}")

    def insert_nudge(self, nudge_text: str):
        """Insert a proactive nudge."""
        try:
            self.conn.execute(
                "INSERT INTO nudges (timestamp, nudge_text) VALUES (?, ?)",
                (datetime.now().isoformat(), nudge_text)
            )
            self.conn.commit()
            logger.debug("Inserted new proactive nudge.")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to insert nudge: {e}")

    # ─── Search Operations ───────────────────────────────────────────

    def search_semantic(
        self, query_embedding: np.ndarray, limit: int = SEARCH_TOP_K
    ) -> list[dict]:
        """
        K-nearest-neighbor search using sqlite-vec.
        Returns list of dicts with capture metadata + distance.
        """
        embedding_bytes = query_embedding.astype(np.float32).tobytes()

        rows = self.conn.execute(
            """
            SELECT
                c.id, c.timestamp, c.source, c.text_content,
                c.window_title, c.process_name, v.distance
            FROM vec_captures v
            JOIN captures c ON c.id = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (embedding_bytes, limit),
        ).fetchall()

        return [dict(row) for row in rows]

    def search_keyword(
        self, query_text: str, limit: int = SEARCH_TOP_K
    ) -> list[dict]:
        """
        Full-text keyword search using FTS5.
        Uses _fts_query to tokenize, drop stopwords, quote terms, and join with OR.
        Returns list of dicts with capture metadata + FTS rank.
        """
        fts_expr = _fts_query(query_text)
        if not fts_expr:
            return []

        try:
            rows = self.conn.execute(
                """
                SELECT
                    c.id, c.timestamp, c.source, c.text_content,
                    c.window_title, c.process_name,
                    captures_fts.rank AS fts_rank
                FROM captures_fts
                JOIN captures c ON c.id = captures_fts.rowid
                WHERE captures_fts MATCH ?
                ORDER BY captures_fts.rank
                LIMIT ?
                """,
                (fts_expr, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS keyword search error on '{fts_expr}': {e}")
            return []

    def search_hybrid(
        self,
        query_text: str,
        query_embedding: Optional[np.ndarray],
        limit: int = SEARCH_TOP_K,
        time_range: Optional[Tuple[str, str]] = None,
    ) -> list[dict]:
        """
        Hybrid search combining semantic + keyword results using
        Reciprocal Rank Fusion (RRF).

        If time_range=(start_time, end_time) is provided:
        - Fetches candidate captures in range via the timestamp index.
        - If pure temporal query (no residual query terms), returns captures spread evenly across window.
        - Computes exact cosine similarity on candidate vectors in numpy.
        - Restricts FTS keyword search to candidate rowids.
        - Fuses rankings with RRF.

        If time_range is None:
        - Runs standard global hybrid search.
        """
        # ─── Time-Filtered Search Path ───────────────────────────────
        if time_range is not None:
            start_time, end_time = time_range
            candidate_rows = self.conn.execute(
                """
                SELECT id, timestamp, source, text_content,
                       window_title, process_name
                FROM captures
                WHERE timestamp BETWEEN ? AND ?
                ORDER BY timestamp ASC
                """,
                (start_time, end_time),
            ).fetchall()

            if not candidate_rows:
                return []

            candidates = [dict(r) for r in candidate_rows]
            candidate_ids = [c["id"] for c in candidates]

            # Pure temporal query: empty residual query
            clean_query = query_text.strip() if query_text else ""
            fts_expr = _fts_query(clean_query)
            is_pure_temporal = (not clean_query) or (fts_expr is None and query_embedding is None)

            if is_pure_temporal:
                if len(candidates) <= limit:
                    return candidates
                step = (len(candidates) - 1) / (limit - 1) if limit > 1 else 1
                indices = [round(i * step) for i in range(limit)]
                return [candidates[idx] for idx in indices]

            # 1. Exact Cosine Similarity in numpy over candidate rowids
            semantic_results = []
            if query_embedding is not None and candidate_ids:
                placeholders = ",".join("?" * len(candidate_ids))
                vec_rows = self.conn.execute(
                    f"SELECT rowid, embedding FROM vec_captures WHERE rowid IN ({placeholders})",
                    candidate_ids,
                ).fetchall()

                rowid_to_emb = {
                    r[0]: np.frombuffer(r[1], dtype=np.float32) for r in vec_rows
                }
                q_norm = float(np.linalg.norm(query_embedding))

                scored = []
                for c in candidates:
                    emb = rowid_to_emb.get(c["id"])
                    if emb is not None and q_norm > 0:
                        e_norm = float(np.linalg.norm(emb))
                        sim = float(np.dot(emb, query_embedding) / (e_norm * q_norm)) if e_norm > 0 else 0.0
                    else:
                        sim = -1.0
                    entry = c.copy()
                    entry["similarity"] = sim
                    scored.append(entry)

                scored.sort(key=lambda x: x["similarity"], reverse=True)
                semantic_results = scored

            # 2. Restricted FTS keyword search on candidate IDs
            keyword_results = []
            if fts_expr and candidate_ids:
                placeholders = ",".join("?" * len(candidate_ids))
                try:
                    fts_rows = self.conn.execute(
                        f"""
                        SELECT c.id, captures_fts.rank AS fts_rank
                        FROM captures_fts
                        JOIN captures c ON c.id = captures_fts.rowid
                        WHERE captures_fts MATCH ? AND c.id IN ({placeholders})
                        ORDER BY captures_fts.rank
                        LIMIT ?
                        """,
                        (fts_expr, *candidate_ids, limit * 2),
                    ).fetchall()

                    cand_map = {c["id"]: c for c in candidates}
                    for fr in fts_rows:
                        cid = fr[0]
                        if cid in cand_map:
                            entry = cand_map[cid].copy()
                            entry["fts_rank"] = fr[1]
                            keyword_results.append(entry)
                except sqlite3.OperationalError as e:
                    logger.warning(f"FTS error in time-filtered search: {e}")

            # 3. Reciprocal Rank Fusion (RRF)
            rrf_scores: dict[int, float] = {}
            result_map: dict[int, dict] = {}

            for rank, result in enumerate(semantic_results):
                rid = result["id"]
                rrf_scores[rid] = rrf_scores.get(rid, 0) + 1.0 / (RRF_K + rank + 1)
                result_map[rid] = result

            for rank, result in enumerate(keyword_results):
                rid = result["id"]
                rrf_scores[rid] = rrf_scores.get(rid, 0) + 1.0 / (RRF_K + rank + 1)
                result_map[rid] = result

            if not rrf_scores:
                # If neither produced rankable hits, evenly sample in-window candidates
                if len(candidates) <= limit:
                    return candidates
                step = (len(candidates) - 1) / (limit - 1) if limit > 1 else 1
                return [candidates[round(i * step)] for i in range(limit)]

            kw_id_set = {k["id"] for k in keyword_results}
            sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)
            results = []
            for rid in sorted_ids[:limit]:
                entry = result_map[rid].copy()
                entry["rrf_score"] = rrf_scores[rid]
                entry["score"] = rrf_scores[rid]
                entry["keyword_match"] = (rid in kw_id_set)
                if "distance" in entry:
                    entry["cosine_sim"] = max(0.0, 1.0 - (entry["distance"] ** 2) / 2.0)
                else:
                    entry["cosine_sim"] = 0.5
                results.append(entry)

            return results

        # ─── Global (Unfiltered) Search Path ─────────────────────────
        semantic_results = (
            self.search_semantic(query_embedding, limit=limit * 2)
            if query_embedding is not None
            else []
        )
        keyword_results = self.search_keyword(query_text, limit=limit * 2)

        # Build RRF scores
        rrf_scores: dict[int, float] = {}
        result_map: dict[int, dict] = {}

        for rank, result in enumerate(semantic_results):
            rid = result["id"]
            rrf_scores[rid] = rrf_scores.get(rid, 0) + 1.0 / (RRF_K + rank + 1)
            result_map[rid] = result

        for rank, result in enumerate(keyword_results):
            rid = result["id"]
            rrf_scores[rid] = rrf_scores.get(rid, 0) + 1.0 / (RRF_K + rank + 1)
            result_map[rid] = result

        kw_id_set = {k["id"] for k in keyword_results}
        sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)

        results = []
        for rid in sorted_ids[:limit]:
            entry = result_map[rid].copy()
            entry["rrf_score"] = rrf_scores[rid]
            entry["score"] = rrf_scores[rid]
            entry["keyword_match"] = (rid in kw_id_set)
            if "distance" in entry:
                entry["cosine_sim"] = max(0.0, 1.0 - (entry["distance"] ** 2) / 2.0)
            else:
                entry["cosine_sim"] = 0.5
            results.append(entry)

        return results

    # ─── Episode Search (Chunk 2) ────────────────────────────────────

    def search_episodes(
        self,
        query_embedding: Optional[np.ndarray],
        query_text: Optional[str] = None,
        limit: int = 10,
        time_range: Optional[Tuple[str, str]] = None,
    ) -> list[dict]:
        """
        Episode-level retrieval (Chunk 2): rank episodes via cosine similarity
        of query embedding vs episode centroid + BM25 over representative text (RRF),
        respecting the time window filter.
        """
        conditions = []
        params = []
        if time_range:
            start_w, end_w = time_range
            conditions.append("end_time >= ?")
            params.append(start_w)
            conditions.append("start_time <= ?")
            params.append(end_w)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        cur = self.conn.cursor()
        ep_rows = cur.execute(
            f"""
            SELECT id, start_time, end_time, process_name, dominant_title,
                   capture_count, centroid, representative_text, representative_capture_id
            FROM episodes
            {where_clause}
            ORDER BY start_time ASC
            """,
            params,
        ).fetchall()

        if not ep_rows:
            return []

        has_text = bool(query_text and query_text.strip())
        if not has_text and query_embedding is None:
            if len(ep_rows) <= limit:
                selected_eps = ep_rows
            else:
                indices = np.linspace(0, len(ep_rows) - 1, limit, dtype=int)
                selected_eps = [ep_rows[i] for i in indices]

            results = []
            for ep in selected_eps:
                cids = [
                    r[0]
                    for r in cur.execute(
                        "SELECT capture_id FROM episode_captures WHERE episode_id = ? ORDER BY capture_id ASC",
                        (ep["id"],),
                    ).fetchall()
                ]
                results.append({
                    "id": ep["id"],
                    "episode_id": ep["id"],
                    "timestamp": ep["start_time"],
                    "start_time": ep["start_time"],
                    "end_time": ep["end_time"],
                    "process_name": ep["process_name"],
                    "dominant_title": ep["dominant_title"],
                    "window_title": ep["dominant_title"],
                    "capture_count": ep["capture_count"],
                    "text_content": ep["representative_text"],
                    "representative_text": ep["representative_text"],
                    "representative_capture_id": ep["representative_capture_id"],
                    "capture_ids": cids,
                    "source": "episode",
                    "score": 1.0,
                })
            return results

        rank_vec = {}
        sim_map = {}
        candidate_ids = [r["id"] for r in ep_rows]
        candidate_id_set = set(candidate_ids)

        if query_embedding is not None:
            centroids = [np.frombuffer(r["centroid"], dtype=np.float32) for r in ep_rows]
            C_mat = np.stack(centroids)
            q_norm_val = np.linalg.norm(query_embedding)
            q_vec = query_embedding / q_norm_val if q_norm_val > 0 else query_embedding
            sims = np.dot(C_mat, q_vec)
            order = np.argsort(-sims)
            for r_idx, idx in enumerate(order):
                ep_id = ep_rows[idx]["id"]
                rank_vec[ep_id] = r_idx
                sim_map[ep_id] = float(sims[idx])

        rank_fts = {}
        if has_text:
            fts_q = _fts_query(query_text)
            if fts_q:
                try:
                    fts_matches = cur.execute(
                        """
                        SELECT rowid, rank FROM episodes_fts
                        WHERE episodes_fts MATCH ?
                        ORDER BY rank
                        """,
                        (fts_q,),
                    ).fetchall()
                    current_rank = 0
                    for rowid, _ in fts_matches:
                        if rowid in candidate_id_set:
                            rank_fts[rowid] = current_rank
                            current_rank += 1
                except sqlite3.OperationalError:
                    pass

        rrf_scores = {}
        for ep_id in candidate_ids:
            score = 0.0
            if ep_id in rank_vec:
                score += 1.0 / (RRF_K + rank_vec[ep_id])
            if ep_id in rank_fts:
                score += 1.0 / (RRF_K + rank_fts[ep_id])
            rrf_scores[ep_id] = score

        sorted_ids = sorted(candidate_ids, key=lambda eid: rrf_scores[eid], reverse=True)[:limit]
        ep_map = {r["id"]: r for r in ep_rows}

        results = []
        for ep_id in sorted_ids:
            ep = ep_map[ep_id]
            cids = [
                r[0]
                for r in cur.execute(
                    "SELECT capture_id FROM episode_captures WHERE episode_id = ? ORDER BY capture_id ASC",
                    (ep_id,),
                ).fetchall()
            ]
            results.append({
                "id": ep["id"],
                "episode_id": ep["id"],
                "timestamp": ep["start_time"],
                "start_time": ep["start_time"],
                "end_time": ep["end_time"],
                "process_name": ep["process_name"],
                "dominant_title": ep["dominant_title"],
                "window_title": ep["dominant_title"],
                "capture_count": ep["capture_count"],
                "text_content": ep["representative_text"],
                "representative_text": ep["representative_text"],
                "representative_capture_id": ep["representative_capture_id"],
                "capture_ids": cids,
                "source": "episode",
                "score": rrf_scores[ep_id],
                "cosine_sim": sim_map.get(ep_id, 0.0),
                "keyword_match": (ep_id in rank_fts),
            })

        return results

    # ─── Query Operations ────────────────────────────────────────────

    def get_captures_in_range(
        self, start_time: str, end_time: str
    ) -> list[dict]:
        """Retrieve all captures within a time range (ISO 8601 strings)."""
        rows = self.conn.execute(
            """
            SELECT id, timestamp, source, text_content,
                   window_title, process_name
            FROM captures
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
            """,
            (start_time, end_time),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_captures(self, limit: int = 20) -> list[dict]:
        """Retrieve the most recent N captures."""
        rows = self.conn.execute(
            """
            SELECT id, timestamp, source, text_content,
                   window_title, process_name
            FROM captures
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_latest_nudge(self) -> Optional[dict]:
        """Get the most recent nudge."""
        row = self.conn.execute(
            "SELECT timestamp, nudge_text FROM nudges ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_stats(self) -> dict:
        """Return database statistics for the CLI status command."""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM captures"
        ).fetchone()[0]

        screen_count = self.conn.execute(
            "SELECT COUNT(*) FROM captures WHERE source = 'screen'"
        ).fetchone()[0]

        audio_count = self.conn.execute(
            "SELECT COUNT(*) FROM captures WHERE source = 'audio'"
        ).fetchone()[0]

        # Database file size
        db_size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        db_size_mb = db_size_bytes / (1024 * 1024)

        # Time range
        first = self.conn.execute(
            "SELECT MIN(timestamp) FROM captures"
        ).fetchone()[0]

        last = self.conn.execute(
            "SELECT MAX(timestamp) FROM captures"
        ).fetchone()[0]

        return {
            "total_captures": total,
            "screen_captures": screen_count,
            "audio_captures": audio_count,
            "db_size_mb": round(db_size_mb, 2),
            "earliest_capture": first,
            "latest_capture": last,
        }

    # ─── Retention / Cleanup ─────────────────────────────────────────

    def cleanup_old_captures(self, retention_days: int = RETENTION_DAYS):
        """
        Delete captures older than retention_days.
        Also removes corresponding FTS and vec entries via triggers + manual vec cleanup.
        """
        if retention_days <= 0:
            return 0

        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

        # Get IDs to delete (needed for vec_captures cleanup)
        ids_to_delete = self.conn.execute(
            "SELECT id FROM captures WHERE timestamp < ?", (cutoff,)
        ).fetchall()

        if not ids_to_delete:
            return 0

        id_list = [row[0] for row in ids_to_delete]

        # Delete from vec_captures (no trigger support for virtual tables)
        placeholders = ",".join("?" * len(id_list))
        self.conn.execute(
            f"DELETE FROM vec_captures WHERE rowid IN ({placeholders})",
            id_list,
        )

        # Delete from captures (FTS cleanup happens via trigger)
        deleted = self.conn.execute(
            "DELETE FROM captures WHERE timestamp < ?", (cutoff,)
        ).rowcount

        self.conn.commit()
        logger.info(
            f"Retention cleanup: deleted {deleted} captures older than "
            f"{retention_days} days"
        )
        return deleted

    # ─── Lifecycle ───────────────────────────────────────────────────

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ─── Standalone Test ─────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)

    print("Testing DatabaseManager...")
    with DatabaseManager() as db:
        # Insert a test capture
        test_embedding = np.random.randn(EMBEDDING_DIM).astype(np.float32)
        row_id = db.insert_capture(
            source="screen",
            text_content="This is a test OCR capture from VS Code editor",
            embedding=test_embedding,
            window_title="test.py - Visual Studio Code",
            process_name="Code.exe",
        )
        print(f"  Inserted test capture with id={row_id}")

        # Insert another
        test_embedding2 = np.random.randn(EMBEDDING_DIM).astype(np.float32)
        row_id2 = db.insert_capture(
            source="audio",
            text_content="Let's discuss the project architecture tomorrow",
            embedding=test_embedding2,
            confidence=0.92,
            duration_secs=30.0,
        )
        print(f"  Inserted test audio capture with id={row_id2}")

        # Keyword search
        kw_results = db.search_keyword("project architecture")
        print(f"  Keyword search 'project architecture': {len(kw_results)} results")

        # Semantic search
        sem_results = db.search_semantic(test_embedding, limit=5)
        print(f"  Semantic search: {len(sem_results)} results")

        # Stats
        stats = db.get_stats()
        print(f"  Stats: {json.dumps(stats, indent=2)}")

        # Recent
        recent = db.get_recent_captures(5)
        print(f"  Recent captures: {len(recent)}")

    print("All database tests passed!")
