"""
Interface Layer — Web UI Server

Flask-based REST API and HTML dashboard for viewing sessions, querying the
RAG agent, visualizing activity analytics, and inspecting grounded episodes.
Zero cloud dependency — 100% local and air-gapped.
"""

import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# Ensure offline environment for HuggingFace / Transformers
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import threading
import requests

import config
from storage.db import DatabaseManager
from intelligence.rag import RAGAgent
from intelligence.nudge_agent import NudgeAgent
from processing.embed import EmbeddingGenerator

logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# Global instances initialized before running the server or lazily
db: Optional[DatabaseManager] = None
embedder: Optional[EmbeddingGenerator] = None
rag_agent: Optional[RAGAgent] = None
nudge_agent: Optional[NudgeAgent] = None
_init_lock = threading.RLock()


def get_db() -> DatabaseManager:
    global db
    if db is None:
        with _init_lock:
            if db is None:
                db = DatabaseManager()
    return db


def get_embedder() -> EmbeddingGenerator:
    global embedder
    if embedder is None:
        with _init_lock:
            if embedder is None:
                embedder = EmbeddingGenerator()
    return embedder


def get_rag() -> RAGAgent:
    global rag_agent
    if rag_agent is None:
        with _init_lock:
            if rag_agent is None:
                database = get_db()
                emb = get_embedder()
                rag_agent = RAGAgent(database, emb)
    return rag_agent


def get_nudge_agent() -> NudgeAgent:
    global nudge_agent
    if nudge_agent is None:
        with _init_lock:
            if nudge_agent is None:
                nudge_agent = NudgeAgent(get_db())
    return nudge_agent


def format_duration(seconds: float) -> str:
    """Format duration in seconds to a human readable string."""
    if seconds <= 0:
        return "0s"
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    rem_secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {rem_secs}s" if rem_secs > 0 else f"{minutes}m"
    hours = int(minutes // 60)
    rem_mins = int(minutes % 60)
    return f"{hours}h {rem_mins}m" if rem_mins > 0 else f"{hours}h"


def parse_iso_datetime(dt_str: str) -> Optional[datetime]:
    """Parse ISO datetime safely."""
    if not dt_str:
        return None
    try:
        # Handle fractional seconds and standard ISO
        return datetime.fromisoformat(dt_str)
    except Exception:
        try:
            return datetime.strptime(dt_str.split(".")[0], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None


def clean_source_dict(s: dict) -> dict:
    """Clean source dict for JSON serialization."""
    out = {}
    for k, v in s.items():
        if k in ("centroid", "embedding"):
            continue
        if hasattr(v, "item"):
            out[k] = v.item()
        elif isinstance(v, (str, int, float, bool, list, dict)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)
    return out


# ─── Page Routes ───────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── Status & Stats Endpoints ──────────────────────────────────────────

@app.route("/api/stats")
def get_stats():
    """Returns DB stats."""
    try:
        database = get_db()
        return jsonify(database.get_stats())
    except Exception as e:
        logger.error(f"Error fetching stats: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/status")
def get_status():
    """Returns system status, active models, offline proof, and stats."""
    try:
        database = get_db()
        db_stats = database.get_stats()

        # Check Ollama online status
        ollama_online = False
        ollama_models = []
        try:
            resp = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=1.0)
            if resp.status_code == 200:
                ollama_online = True
                ollama_models = [m.get("name") for m in resp.json().get("models", [])]
        except Exception:
            ollama_online = False

        # Count episodes
        cur = database.conn.cursor()
        ep_count = cur.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]

        return jsonify({
            "status": "online",
            "offline_mode": True,
            "zero_telemetry": True,
            "ollama_online": ollama_online,
            "ollama_models": ollama_models,
            "active_model": config.OLLAMA_MODEL,
            "embedding_model": config.EMBEDDING_MODEL,
            "use_temporal": config.USE_TEMPORAL,
            "use_episodes": config.USE_EPISODES,
            "use_grounding": config.USE_GROUNDING,
            "capture_interval_secs": config.CAPTURE_INTERVAL_SECS,
            "total_captures": db_stats.get("total_captures", 0),
            "total_episodes": ep_count,
            "db_size_mb": db_stats.get("db_size_mb", 0.0),
            "earliest_capture": db_stats.get("earliest_capture"),
            "latest_capture": db_stats.get("latest_capture"),
        })
    except Exception as e:
        logger.error(f"Error fetching system status: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ─── Chat Endpoint ─────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def chat():
    """RAG agent query endpoint with grounding verification."""
    data = request.json or {}
    question = data.get("question", "").strip()
    top_k = int(data.get("top_k", config.SEARCH_TOP_K))
    if not question:
        return jsonify({"error": "Question is required"}), 400

    try:
        agent = get_rag()
        result = agent.query(question, top_k=top_k)

        raw_sources = result.get("sources", [])
        cleaned_sources = [clean_source_dict(s) for s in raw_sources]

        # Extract temporal parse info if present
        temporal_info = None
        t_parse = result.get("temporal_parse")
        if t_parse:
            if hasattr(t_parse, "to_dict"):
                temporal_info = t_parse.to_dict()
            elif isinstance(t_parse, dict):
                temporal_info = t_parse
            else:
                temporal_info = {
                    "time_range": getattr(t_parse, "time_range", None),
                    "residual_query": getattr(t_parse, "residual_query", ""),
                    "is_temporal": getattr(t_parse, "is_temporal", False),
                }

        return jsonify({
            "answer": result.get("answer", "No answer generated."),
            "sources": cleaned_sources,
            "search_time_ms": round(result.get("search_time_ms", 0), 1),
            "generate_time_ms": round(result.get("generate_time_ms", 0), 1),
            "grounding_rate": result.get("grounding_rate"),
            "partially_verified": result.get("partially_verified", False),
            "refused": result.get("refused", False),
            "refusal_reason": result.get("refusal_reason"),
            "temporal_parse": temporal_info,
        })
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return jsonify({"error": f"Failed to generate answer: {str(e)}"}), 500


@app.route("/api/capture_now", methods=["POST"])
def capture_now():
    """Triggers an instant manual screen capture and indexes it immediately."""
    try:
        from capture.screen_capture import get_active_window_info
        title, proc = get_active_window_info()
        now_iso = datetime.now().isoformat()

        # Capture frame via mss if available
        text_content = f"Manual screen capture from {title} ({proc})"
        try:
            import mss
            import cv2
            import numpy as np
            with mss.mss() as sct:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(monitor)
                frame = np.array(sct_img)[:, :, :3]

            from processing.ocr import OCRProcessor
            ocr = OCRProcessor()
            res = ocr.process(frame, timestamp=now_iso, window_title=title, process_name=proc)
            if res and res.text and len(res.text.strip()) > 5:
                text_content = res.text
        except Exception as ocr_err:
            logger.debug(f"Direct OCR during manual capture: {ocr_err}")

        # Redact PII
        try:
            from processing.redact import PIIRedactor
            redactor = PIIRedactor()
            text_content = redactor.redact(text_content)
        except Exception:
            pass

        # Generate embedding
        emb = get_embedder().generate(text_content)
        database = get_db()
        row_id = database.insert_capture(
            source="screen",
            text_content=text_content,
            embedding=emb,
            window_title=title,
            process_name=proc,
            timestamp=now_iso,
        )

        # Trigger lightweight episode update for current window
        if config.USE_EPISODES:
            try:
                from datetime import timedelta
                from intelligence.segmenter import build_episodes
                window_start = (datetime.fromisoformat(now_iso) - timedelta(minutes=5)).isoformat()
                build_episodes(database, start=window_start, end=now_iso, replace_existing=True)
            except Exception as ep_err:
                logger.debug(f"Episode segmenter update note: {ep_err}")

        return jsonify({
            "status": "success",
            "id": row_id,
            "window_title": title,
            "process_name": proc,
            "timestamp": now_iso,
            "text_length": len(text_content),
        })
    except Exception as e:
        logger.error(f"Manual capture error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ─── Episodes & Timeline Endpoints ─────────────────────────────────────

@app.route("/api/episodes")
def get_episodes():
    """Returns segmented episodes with filters for date, process, keyword, and pagination."""
    try:
        database = get_db()
        cur = database.conn.cursor()

        limit = min(int(request.args.get("limit", 50)), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
        process_filter = request.args.get("process", "").strip()
        date_filter = request.args.get("date", "").strip()
        keyword = request.args.get("q", "").strip()

        conditions = []
        params = []

        if date_filter:
            conditions.append("start_time LIKE ?")
            params.append(f"{date_filter}%")

        if process_filter and process_filter.lower() != "all":
            conditions.append("process_name = ?")
            params.append(process_filter)

        if keyword:
            conditions.append("(dominant_title LIKE ? OR representative_text LIKE ?)")
            kw_param = f"%{keyword}%"
            params.extend([kw_param, kw_param])

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        # Total matching
        count_query = f"SELECT COUNT(*) FROM episodes {where_clause}"
        total_count = cur.execute(count_query, params).fetchone()[0]

        # Fetch episodes
        query = f"""
            SELECT id, start_time, end_time, process_name, dominant_title,
                   capture_count, representative_text, representative_capture_id
            FROM episodes
            {where_clause}
            ORDER BY start_time DESC
            LIMIT ? OFFSET ?
        """
        rows = cur.execute(query, params + [limit, offset]).fetchall()

        episodes = []
        for r in rows:
            ep = dict(r)
            # Calculate duration
            st = parse_iso_datetime(ep["start_time"])
            et = parse_iso_datetime(ep["end_time"])
            duration_secs = (et - st).total_seconds() if st and et else 0.0
            if duration_secs < 0:
                duration_secs = 0.0
            ep["duration_secs"] = duration_secs
            ep["duration_formatted"] = format_duration(duration_secs)
            episodes.append(ep)

        # Distinct processes for dropdown
        proc_rows = cur.execute(
            "SELECT DISTINCT process_name FROM episodes WHERE process_name IS NOT NULL ORDER BY process_name ASC"
        ).fetchall()
        processes = [pr[0] for pr in proc_rows if pr[0]]

        return jsonify({
            "episodes": episodes,
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "processes": processes,
        })
    except Exception as e:
        logger.error(f"Error fetching episodes: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/episodes/<int:episode_id>")
def get_episode_detail(episode_id: int):
    """Returns details and all child captures for a single episode."""
    try:
        database = get_db()
        cur = database.conn.cursor()

        ep_row = cur.execute(
            """
            SELECT id, start_time, end_time, process_name, dominant_title,
                   capture_count, representative_text, representative_capture_id
            FROM episodes
            WHERE id = ?
            """,
            (episode_id,)
        ).fetchone()

        if not ep_row:
            return jsonify({"error": "Episode not found"}), 404

        episode = dict(ep_row)
        st = parse_iso_datetime(episode["start_time"])
        et = parse_iso_datetime(episode["end_time"])
        duration_secs = (et - st).total_seconds() if st and et else 0.0
        episode["duration_secs"] = duration_secs
        episode["duration_formatted"] = format_duration(duration_secs)

        # Associated captures
        captures_rows = cur.execute(
            """
            SELECT c.id, c.timestamp, c.source, c.text_content, c.window_title, c.process_name
            FROM episode_captures ec
            JOIN captures c ON c.id = ec.capture_id
            WHERE ec.episode_id = ?
            ORDER BY c.timestamp ASC
            """,
            (episode_id,)
        ).fetchall()

        captures = [dict(cr) for cr in captures_rows]

        return jsonify({
            "episode": episode,
            "captures": captures,
        })
    except Exception as e:
        logger.error(f"Error fetching episode detail: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ─── Activity Analytics & Recap Endpoints ──────────────────────────────

@app.route("/api/activity")
def get_activity():
    """Computes screen-time analytics, app distribution, and hourly heatmap."""
    try:
        database = get_db()
        cur = database.conn.cursor()

        date_param = request.args.get("date", "").strip()

        # Find available dates
        date_rows = cur.execute(
            """
            SELECT DISTINCT substr(timestamp, 1, 10) as dt
            FROM captures
            WHERE dt IS NOT NULL
            ORDER BY dt DESC
            """
        ).fetchall()
        available_dates = [r[0] for r in date_rows if r[0]]

        target_date = date_param if date_param else (available_dates[0] if available_dates else datetime.now().strftime("%Y-%m-%d"))

        # Fetch episodes on target_date
        ep_rows = cur.execute(
            """
            SELECT id, start_time, end_time, process_name, dominant_title, capture_count
            FROM episodes
            WHERE start_time LIKE ?
            ORDER BY start_time ASC
            """,
            (f"{target_date}%",)
        ).fetchall()

        total_active_seconds = 0.0
        app_durations: Dict[str, float] = {}
        app_episodes: Dict[str, int] = {}
        window_counts: Dict[str, int] = {}

        for r in ep_rows:
            st = parse_iso_datetime(r["start_time"])
            et = parse_iso_datetime(r["end_time"])
            dur = (et - st).total_seconds() if st and et else float(config.CAPTURE_INTERVAL_SECS * r["capture_count"])
            dur = max(dur, float(config.CAPTURE_INTERVAL_SECS * r["capture_count"]))
            total_active_seconds += dur

            proc = r["process_name"] or "Unknown"
            app_durations[proc] = app_durations.get(proc, 0.0) + dur
            app_episodes[proc] = app_episodes.get(proc, 0) + 1

            title = r["dominant_title"] or "Untitled"
            window_counts[title] = window_counts.get(title, 0) + 1

        # App breakdown sorted
        app_breakdown = []
        for proc, dur in sorted(app_durations.items(), key=lambda x: x[1], reverse=True):
            pct = round((dur / total_active_seconds * 100), 1) if total_active_seconds > 0 else 0
            app_breakdown.append({
                "process_name": proc,
                "duration_seconds": round(dur, 1),
                "duration_formatted": format_duration(dur),
                "percentage": pct,
                "episode_count": app_episodes.get(proc, 0),
            })

        # Hourly distribution for target_date (24 buckets)
        hourly_counts = [0] * 24
        cap_hour_rows = cur.execute(
            """
            SELECT substr(timestamp, 12, 2) as hr, COUNT(*)
            FROM captures
            WHERE timestamp LIKE ?
            GROUP BY hr
            """,
            (f"{target_date}%",)
        ).fetchall()

        for hr_str, cnt in cap_hour_rows:
            try:
                hr_int = int(hr_str)
                if 0 <= hr_int < 24:
                    hourly_counts[hr_int] = cnt
            except Exception:
                pass

        hourly_distribution = [
            {"hour": h, "label": f"{h:02d}:00", "count": hourly_counts[h]}
            for h in range(24)
        ]

        # Top windows
        top_windows = [
            {"window_title": title, "count": count}
            for title, count in sorted(window_counts.items(), key=lambda x: x[1], reverse=True)[:6]
        ]

        # Captures count for date
        day_captures = cur.execute(
            "SELECT COUNT(*) FROM captures WHERE timestamp LIKE ?",
            (f"{target_date}%",)
        ).fetchone()[0]

        return jsonify({
            "date": target_date,
            "available_dates": available_dates,
            "total_active_seconds": round(total_active_seconds, 1),
            "total_active_formatted": format_duration(total_active_seconds),
            "total_episodes": len(ep_rows),
            "total_captures": day_captures,
            "app_breakdown": app_breakdown,
            "hourly_distribution": hourly_distribution,
            "top_windows": top_windows,
        })
    except Exception as e:
        logger.error(f"Error computing activity: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/recap")
def get_day_recap():
    """Generates structured day recap based on captured episodes."""
    try:
        database = get_db()
        cur = database.conn.cursor()

        date_param = request.args.get("date", "").strip()
        date_rows = cur.execute(
            "SELECT DISTINCT substr(timestamp, 1, 10) as dt FROM captures ORDER BY dt DESC"
        ).fetchall()
        available_dates = [r[0] for r in date_rows if r[0]]
        target_date = date_param if date_param else (available_dates[0] if available_dates else datetime.now().strftime("%Y-%m-%d"))

        ep_rows = cur.execute(
            """
            SELECT id, start_time, end_time, process_name, dominant_title, capture_count, representative_text
            FROM episodes
            WHERE start_time LIKE ?
            ORDER BY start_time ASC
            """,
            (f"{target_date}%",)
        ).fetchall()

        if not ep_rows:
            return jsonify({
                "date": target_date,
                "summary": "No activity recorded for this day.",
                "total_time": "0s",
                "highlights": [],
                "top_apps": [],
            })

        app_time = {}
        total_secs = 0.0
        unique_tasks = []
        seen_titles = set()

        for r in ep_rows:
            st = parse_iso_datetime(r["start_time"])
            et = parse_iso_datetime(r["end_time"])
            dur = (et - st).total_seconds() if st and et else float(config.CAPTURE_INTERVAL_SECS * r["capture_count"])
            dur = max(dur, float(config.CAPTURE_INTERVAL_SECS * r["capture_count"]))
            total_secs += dur

            proc = r["process_name"] or "Unknown"
            app_time[proc] = app_time.get(proc, 0.0) + dur

            title = (r["dominant_title"] or "").strip()
            if title and title not in seen_titles and len(title) > 3:
                seen_titles.add(title)
                st_time_str = st.strftime("%I:%M %p") if st else ""
                unique_tasks.append({
                    "time": st_time_str,
                    "process": proc,
                    "title": title,
                    "duration": format_duration(dur),
                    "text_preview": (r["representative_text"] or "")[:140],
                })

        sorted_apps = sorted(app_time.items(), key=lambda x: x[1], reverse=True)
        top_apps_list = [{"process": k, "duration": format_duration(v)} for k, v in sorted_apps[:4]]

        top_app_name = sorted_apps[0][0] if sorted_apps else "your workspace"
        total_fmt = format_duration(total_secs)

        summary_text = (
            f"On {target_date}, you were active for {total_fmt} across {len(ep_rows)} episodes. "
            f"Your primary focus was on {top_app_name} with key work across "
            f"{len(unique_tasks)} distinct window tasks."
        )

        return jsonify({
            "date": target_date,
            "total_time": total_fmt,
            "total_episodes": len(ep_rows),
            "summary": summary_text,
            "top_apps": top_apps_list,
            "highlights": unique_tasks[:8],
        })
    except Exception as e:
        logger.error(f"Error generating recap: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ─── Fast Search Endpoint ──────────────────────────────────────────────

@app.route("/api/search")
def fast_search():
    """Instant search without LLM generation over captures and episodes."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"episodes": [], "captures": []})

    try:
        database = get_db()
        cur = database.conn.cursor()

        # Keyword search on episodes FTS
        ep_matches = []
        try:
            ep_rows = cur.execute(
                """
                SELECT e.id, e.start_time, e.end_time, e.process_name, e.dominant_title,
                       e.capture_count, e.representative_text
                FROM episodes_fts ef
                JOIN episodes e ON e.id = ef.rowid
                WHERE episodes_fts MATCH ?
                LIMIT 15
                """,
                (f'"{query}"',),
            ).fetchall()
            for r in ep_rows:
                ep = dict(r)
                st = parse_iso_datetime(ep["start_time"])
                et = parse_iso_datetime(ep["end_time"])
                dur = (et - st).total_seconds() if st and et else 0
                ep["duration_formatted"] = format_duration(dur)
                ep_matches.append(ep)
        except Exception:
            # Fallback to LIKE
            ep_rows = cur.execute(
                """
                SELECT id, start_time, end_time, process_name, dominant_title, capture_count, representative_text
                FROM episodes
                WHERE dominant_title LIKE ? OR representative_text LIKE ?
                ORDER BY start_time DESC
                LIMIT 15
                """,
                (f"%{query}%", f"%{query}%"),
            ).fetchall()
            for r in ep_rows:
                ep = dict(r)
                st = parse_iso_datetime(ep["start_time"])
                et = parse_iso_datetime(ep["end_time"])
                dur = (et - st).total_seconds() if st and et else 0
                ep["duration_formatted"] = format_duration(dur)
                ep_matches.append(ep)

        # Keyword search on captures FTS
        cap_matches = []
        try:
            cap_rows = cur.execute(
                """
                SELECT c.id, c.timestamp, c.source, c.text_content, c.window_title, c.process_name
                FROM captures_fts cf
                JOIN captures c ON c.id = cf.rowid
                WHERE captures_fts MATCH ?
                LIMIT 15
                """,
                (f'"{query}"',),
            ).fetchall()
            cap_matches = [dict(r) for r in cap_rows]
        except Exception:
            cap_rows = cur.execute(
                """
                SELECT id, timestamp, source, text_content, window_title, process_name
                FROM captures
                WHERE text_content LIKE ? OR window_title LIKE ?
                ORDER BY timestamp DESC
                LIMIT 15
                """,
                (f"%{query}%", f"%{query}%"),
            ).fetchall()
            cap_matches = [dict(r) for r in cap_rows]

        return jsonify({
            "query": query,
            "episodes": ep_matches,
            "captures": cap_matches,
        })
    except Exception as e:
        logger.error(f"Error in fast search: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ─── Nudge & Compatibility Endpoints ───────────────────────────────────

@app.route("/api/nudge")
def get_nudge():
    """Generates or retrieves a proactive nudge."""
    try:
        database = get_db()
        latest = database.get_latest_nudge()
        if latest:
            return jsonify({"nudge": latest.get("nudge_text")})

        agent = get_nudge_agent()
        nudge = agent.evaluate_recent_activity(hours=2.0)
        if nudge:
            database.insert_nudge(nudge)
            return jsonify({"nudge": nudge})
        else:
            return jsonify({"nudge": "Great progress today! Stay focused and remember to take short breaks."})
    except Exception as e:
        logger.warning(f"Nudge evaluation note: {e}")
        return jsonify({"nudge": "Focused work detected. Keep up the steady cadence!"})


@app.route("/api/sessions")
def get_sessions():
    """Returns the most recent N sessions."""
    try:
        limit = int(request.args.get("limit", 10))
        database = get_db()
        rows = database.conn.execute(
            """
            SELECT id, start_time, end_time, label
            FROM sessions
            ORDER BY start_time DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/recent")
def get_recent_captures():
    """Returns recent raw captures."""
    try:
        limit = int(request.args.get("limit", 20))
        database = get_db()
        captures = database.get_recent_captures(limit)
        return jsonify(captures)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/settings", methods=["GET", "POST"])
def settings_handler():
    """Get or update engine settings."""
    if request.method == "POST":
        data = request.json or {}
        if "use_temporal" in data:
            config.USE_TEMPORAL = bool(data["use_temporal"])
        if "use_episodes" in data:
            config.USE_EPISODES = bool(data["use_episodes"])
        if "use_grounding" in data:
            config.USE_GROUNDING = bool(data["use_grounding"])
        if "ollama_model" in data and data["ollama_model"]:
            config.OLLAMA_MODEL = str(data["ollama_model"])

    return jsonify({
        "use_temporal": config.USE_TEMPORAL,
        "use_episodes": config.USE_EPISODES,
        "use_grounding": config.USE_GROUNDING,
        "ollama_model": config.OLLAMA_MODEL,
        "capture_interval_secs": config.CAPTURE_INTERVAL_SECS,
        "retention_days": config.RETENTION_DAYS,
    })


# ─── Server Startup ────────────────────────────────────────────────────

def start_server(database: DatabaseManager, embedder_inst, port: int = 5000):
    """Starts the Flask server in a background thread."""
    global db, embedder, rag_agent, nudge_agent
    db = database
    embedder = embedder_inst
    rag_agent = RAGAgent(db, embedder)
    nudge_agent = NudgeAgent(db)

    logger.info(f"Starting Web UI on http://127.0.0.1:{port}")
    thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()
    return thread


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db = DatabaseManager()
    embedder = EmbeddingGenerator()
    rag_agent = RAGAgent(db, embedder)
    nudge_agent = NudgeAgent(db)
    app.run(host="127.0.0.1", port=5000, debug=True)
