"""
Intelligence Layer — RAG (Retrieval-Augmented Generation) Agent

Answers natural-language questions about your activity history by:
1. Embedding the question
2. Running hybrid search (semantic + keyword) over the captures database
3. Constructing a context-rich prompt
4. Generating an answer via Ollama (local LLM)

Zero cloud dependency — everything runs on localhost.
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Optional, Union, Dict, Any, List

import requests
import numpy as np

import config
from config import (
    OLLAMA_BASE_URL, OLLAMA_MODEL, LLM_CONTEXT_MAX_CHARS, SEARCH_TOP_K,
    USE_TEMPORAL, USE_EPISODES, USE_GROUNDING, CAPTURE_INTERVAL_SECS,
    REFUSAL_SIM_FLOOR, GROUNDING_MIN, CITATION_TOLERANCE_MINUTES,
    ALLOW_TEMPLATE_FALLBACK
)


def is_template_fallback_allowed() -> bool:
    """Check whether template fallback is permitted or if eval must strictly abort."""
    env_val = os.environ.get("ALLOW_TEMPLATE_FALLBACK")
    if env_val is not None:
        return env_val.lower() in ("true", "1", "yes")
    return getattr(config, "ALLOW_TEMPLATE_FALLBACK", True)
from storage.db import DatabaseManager
from processing.embed import EmbeddingGenerator
from intelligence.temporal import parse_temporal, TemporalParse
from intelligence.segmenter import ensure_episodes
from intelligence.grounding import (
    check_pregeneration_refusals,
    verify_grounding,
    synthesize_grounded_answer,
    GroundingResult,
)

logger = logging.getLogger(__name__)

# ─── Prompt Templates ────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a personal productivity assistant with access to the user's captured screen text and audio transcripts. Your job is to answer questions about what the user has been working on, reading, or discussing.

Rules:
- Answer based ONLY on the provided context. Do not make things up.
- Cite timestamps and window/app names when referencing specific activities.
- If the context doesn't contain enough information to answer, say so honestly.
- Be concise and actionable in your responses.
- Format timestamps in a human-readable way (e.g., "today at 2:30 PM" or "yesterday at 10 AM")."""

SYSTEM_PROMPT_GROUNDED = """You are a personal productivity assistant with access to the user's captured screen text and audio transcripts. Your job is to answer questions about what the user has been working on, reading, or discussing.

Rules:
- Answer based ONLY on the provided context. Do not make things up.
- Every factual claim MUST cite its source using inline citation tags like [E12] or [C5] immediately after the claim.
- Any time or timestamp you mention MUST match the cited source's time span.
- If the context doesn't contain enough information to answer, state that you do not have sufficient information.
- Format timestamps in a human-readable way (e.g., "today at 2:30 PM" or "yesterday at 10 AM")."""

CONTEXT_TEMPLATE = """Here are the user's recent captured activities, ordered by relevance:

{context_entries}

---
User's question: {question}

Answer based on the captured context above:"""

CONTEXT_TEMPLATE_GROUNDED = """Here are the user's recent captured activities, ordered by relevance:

{context_entries}

---
User's question: {question}

Answer based on the captured context above. Remember to cite every factual claim inline with [E<id>] or [C<id>]:"""


class RAGAgent:
    """Local RAG agent that queries the captures database and generates
    answers using a local LLM via Ollama."""

    def __init__(
        self,
        db: DatabaseManager,
        embedder: EmbeddingGenerator,
        model: Optional[str] = None,
    ):
        self.db = db
        self.embedder = embedder
        self.model = model
        self.last_ollama_stats: Dict[str, Any] = {}
        self._verify_ollama()

    def get_model(self) -> str:
        """Get the model to use, checking instance attribute, env var, or config dynamically."""
        if getattr(self, "model", None):
            return self.model
        env_model = os.environ.get("OLLAMA_MODEL")
        if env_model:
            return env_model
        return getattr(config, "OLLAMA_MODEL", "llama3.2:3b-instruct-q4_K_M")

    def _verify_ollama(self):
        """Check that Ollama is running and the model is available."""
        target_model = self.get_model()
        try:
            resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=(1.0, 2.0))
            resp.raise_for_status()
            models = resp.json().get("models", [])
            model_names = [m["name"] for m in models]

            if target_model not in model_names:
                # Try matching by base name / prefix if not an exact match
                base_target = target_model.split(":")[0]
                matching = [m["name"] for m in models if m["name"].startswith(base_target)]
                if matching:
                    logger.info(
                        f"Target model '{target_model}' resolved to available model '{matching[0]}'."
                    )
                    self.model = matching[0]
                    target_model = self.model
                else:
                    logger.warning(
                        f"Model '{target_model}' not found in Ollama. "
                        f"Available: {model_names}. "
                        f"Run: ollama pull {target_model}"
                    )
                    return

            logger.info(f"Ollama verified: model '{target_model}' available")

        except requests.ConnectionError:
            logger.warning(
                f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. "
                "Make sure Ollama is running: `ollama serve`"
            )
        except Exception as e:
            logger.warning(f"Ollama verification issue: {e}")

    def _format_context(self, results: list[dict]) -> str:
        """Format search results into a context string for the LLM prompt."""
        entries = []
        total_chars = 0

        for i, r in enumerate(results, 1):
            if r.get("source") == "episode":
                ep_id = r.get("episode_id") or r.get("id")
                source_icon = "📦"
                app_info = f"App: {r.get('process_name') or 'Unknown'}"
                title_info = f" | Title: {r.get('dominant_title') or r.get('window_title') or 'Unknown'}"
                count_info = f" ({r.get('capture_count', 1)} captures)"
                time_info = f"{r.get('start_time')} to {r.get('end_time')}"
                header = f"[E{ep_id}] {source_icon} Episode {ep_id} [{time_info}] {app_info}{title_info}{count_info}"
            else:
                cap_id = r.get("id")
                source_icon = "🖥️" if r.get("source") == "screen" else "🎤"
                window_info = ""
                if r.get("window_title"):
                    window_info = f" | Window: {r['window_title']}"
                app_info = f" | App: {r.get('process_name') or 'Unknown'}"
                header = f"[C{cap_id}] {source_icon} Capture {cap_id} [{r.get('timestamp')}]{app_info}{window_info}"

            text = r.get("text_content") or r.get("representative_text") or ""

            # Truncate individual entries if needed
            if total_chars + len(text) > LLM_CONTEXT_MAX_CHARS:
                remaining = LLM_CONTEXT_MAX_CHARS - total_chars
                if remaining < 100:
                    break
                text = text[:remaining] + "..."

            entry = f"{header}\n    {text}"
            entries.append(entry)
            total_chars += len(text)

        return "\n\n".join(entries)

    def query(
        self,
        question: str,
        top_k: int = SEARCH_TOP_K,
        reference_now: Optional[Union[str, datetime]] = None,
    ) -> dict:
        """
        Answer a question about the user's activity history.
        When USE_TEMPORAL is enabled, applies temporal query decomposition,
        deterministic refusals, structured aggregate operators, and time-filtered search.

        Returns a dict with:
            - answer: The LLM-generated answer or structured summary
            - sources: The retrieved context entries
            - search_time_ms: How long retrieval took
            - generate_time_ms: How long LLM generation took
            - refused: bool indicating if system deterministically refused
            - refusal_reason: Optional string explanation
            - temporal_parse: Optional dict with temporal parse details
        """
        total_start = time.time()

        # Resolve reference datetime
        if reference_now is not None:
            if isinstance(reference_now, str):
                now = datetime.fromisoformat(reference_now)
            else:
                now = reference_now
        else:
            now = datetime.now()

        # ─── Temporal Decomposition Path (if enabled) ────────────────
        if USE_TEMPORAL:
            parse = parse_temporal(question, now=now)

            # 1. Deterministic Refusal: Future expression
            if parse.is_future:
                stats = self.db.get_stats()
                latest = stats.get("latest_capture") or "the present"
                return {
                    "answer": (
                        "I cannot predict future activities. My context only covers past "
                        f"recorded activities up to {latest}."
                    ),
                    "sources": [],
                    "search_time_ms": 0,
                    "generate_time_ms": 0,
                    "refused": True,
                    "refusal_reason": "future_time",
                    "grounding_rate": 1.0,
                    "partially_verified": False,
                    "temporal_parse": parse.__dict__,
                    "answer_source": "refusal_gate",
                    "ollama_stats": getattr(self, "last_ollama_stats", {}),
                }

            # 2. Deterministic Refusal: Explicit window with 0 captures
            if parse.start and parse.end:
                count_row = self.db.conn.execute(
                    "SELECT COUNT(*) FROM captures WHERE timestamp BETWEEN ? AND ?",
                    (parse.start, parse.end),
                ).fetchone()
                count = count_row[0] if count_row else 0

                if count == 0:
                    stats = self.db.get_stats()
                    earliest = stats.get("earliest_capture") or "unknown"
                    latest = stats.get("latest_capture") or "unknown"
                    return {
                        "answer": (
                            f"I don't have any captured context between {parse.start} and {parse.end}. "
                            f"My recorded activity only covers from {earliest} to {latest}."
                        ),
                        "sources": [],
                        "search_time_ms": 0,
                        "generate_time_ms": 0,
                        "refused": True,
                        "refusal_reason": "no_data_in_range",
                        "grounding_rate": 1.0,
                        "partially_verified": False,
                        "temporal_parse": parse.__dict__,
                        "answer_source": "refusal_gate",
                        "ollama_stats": getattr(self, "last_ollama_stats", {}),
                    }

            # 3. Structured Temporal Operators for Aggregate Intents
            if parse.intent != "search" and parse.start and parse.end:
                search_start = time.time()
                structured_ans = ""
                sources = []

                if parse.intent == "apps":
                    app_rows = self.db.conn.execute(
                        """
                        SELECT DISTINCT process_name, window_title
                        FROM captures
                        WHERE timestamp BETWEEN ? AND ?
                          AND (process_name IS NOT NULL OR window_title IS NOT NULL)
                        ORDER BY process_name
                        """,
                        (parse.start, parse.end),
                    ).fetchall()

                    if USE_EPISODES:
                        ensure_episodes(self.db, start=parse.start, end=parse.end)
                        sources = self.db.search_episodes(
                            query_embedding=None,
                            query_text=None,
                            limit=top_k,
                            time_range=(parse.start, parse.end),
                        )
                    else:
                        sample_rows = self.db.conn.execute(
                            """
                            SELECT id, timestamp, source, text_content, window_title, process_name
                            FROM captures
                            WHERE timestamp BETWEEN ? AND ?
                            ORDER BY timestamp ASC
                            LIMIT ?
                            """,
                            (parse.start, parse.end, top_k),
                        ).fetchall()
                        sources = [dict(r) for r in sample_rows]

                    app_list = []
                    for idx, r in enumerate(app_rows):
                        cite = ""
                        if USE_GROUNDING and sources:
                            s_item = sources[idx % len(sources)]
                            sid = s_item.get("episode_id") or s_item.get("id")
                            tag = f"[E{sid}]" if s_item.get("source") == "episode" else f"[C{sid}]"
                            cite = f" {tag}"
                        app_list.append(
                            f"- {r['process_name'] or 'Process'} (Window: {r['window_title'] or 'None'}){cite}"
                        )
                    structured_ans = (
                        f"Applications and windows used between {parse.start} and {parse.end}:\n"
                        + "\n".join(app_list)
                    )

                elif parse.intent == "duration":
                    # Check for target process name in residual query (e.g. Chrome, VS Code)
                    target = parse.residual_query.strip()
                    if target:
                        pat = f"%{target.lower()}%"
                        dur_rows = self.db.conn.execute(
                            """
                            SELECT timestamp FROM captures
                            WHERE timestamp BETWEEN ? AND ?
                              AND (LOWER(process_name) LIKE ? OR LOWER(window_title) LIKE ?)
                            ORDER BY timestamp ASC
                            """,
                            (parse.start, parse.end, pat, pat),
                        ).fetchall()
                        sample_rows = self.db.conn.execute(
                            """
                            SELECT id, timestamp, source, text_content, window_title, process_name
                            FROM captures
                            WHERE timestamp BETWEEN ? AND ?
                              AND (LOWER(process_name) LIKE ? OR LOWER(window_title) LIKE ?)
                            ORDER BY timestamp ASC
                            LIMIT ?
                            """,
                            (parse.start, parse.end, pat, pat, top_k),
                        ).fetchall()
                    else:
                        dur_rows = self.db.conn.execute(
                            "SELECT timestamp FROM captures WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp ASC",
                            (parse.start, parse.end),
                        ).fetchall()
                        sample_rows = self.db.conn.execute(
                            """
                            SELECT id, timestamp, source, text_content, window_title, process_name
                            FROM captures WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp ASC LIMIT ?
                            """,
                            (parse.start, parse.end, top_k),
                        ).fetchall()

                    sources = [dict(r) for r in sample_rows]
                    ts_list = [datetime.fromisoformat(r[0]) for r in dur_rows]
                    max_gap = 2 * CAPTURE_INTERVAL_SECS
                    total_active_secs = 0.0
                    gaps_count = 0

                    for idx in range(len(ts_list) - 1):
                        gap = (ts_list[idx + 1] - ts_list[idx]).total_seconds()
                        if gap <= max_gap:
                            total_active_secs += gap
                        else:
                            gaps_count += 1

                    if ts_list and total_active_secs == 0:
                        total_active_secs = len(ts_list) * CAPTURE_INTERVAL_SECS

                    mins = total_active_secs / 60.0
                    uncertainty = (
                        f" (Notice: {gaps_count} inactivity gaps exceeding {max_gap}s observed)"
                        if gaps_count > 0
                        else ""
                    )
                    app_name = target or "active window"
                    cite = ""
                    if USE_GROUNDING and sources:
                        cid = sources[0]["id"]
                        tag = f"[E{cid}]" if sources[0].get("source") == "episode" else f"[C{cid}]"
                        cite = f" {tag}"
                    structured_ans = (
                        f"You spent approximately {mins:.1f} minutes active on {app_name} "
                        f"between {parse.start} and {parse.end}{cite}.{uncertainty}"
                    )

                elif parse.intent == "latest":
                    if USE_EPISODES:
                        ensure_episodes(self.db, start=parse.start, end=parse.end)
                        lat_rows = self.db.conn.execute(
                            """
                            SELECT id, start_time, end_time, process_name, dominant_title,
                                   capture_count, representative_text, representative_capture_id
                            FROM episodes
                            WHERE start_time BETWEEN ? AND ?
                            ORDER BY end_time DESC
                            LIMIT ?
                            """,
                            (parse.start, parse.end, top_k),
                        ).fetchall()
                        sources = []
                        for ep in lat_rows:
                            cids = [r[0] for r in self.db.conn.execute("SELECT capture_id FROM episode_captures WHERE episode_id = ? ORDER BY capture_id ASC", (ep["id"],)).fetchall()]
                            sources.append({
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
                            })
                    else:
                        lat_rows = self.db.conn.execute(
                            """
                            SELECT id, timestamp, source, text_content, window_title, process_name
                            FROM captures
                            WHERE timestamp BETWEEN ? AND ?
                            ORDER BY timestamp DESC
                            LIMIT ?
                            """,
                            (parse.start, parse.end, top_k),
                        ).fetchall()
                        sources = [dict(r) for r in lat_rows]

                    if sources:
                        last_c = sources[0]
                        title = last_c.get("dominant_title") or last_c.get("window_title")
                        cite = ""
                        if USE_GROUNDING:
                            cid = last_c.get("episode_id") or last_c.get("id")
                            tag = f"[E{cid}]" if last_c.get("source") == "episode" else f"[C{cid}]"
                            cite = f" {tag}"
                        structured_ans = (
                            f"The last activity recorded on {parse.start[:10]} was at {last_c['timestamp']} "
                            f"in window '{title}' ({last_c['process_name']}){cite}."
                        )

                elif parse.intent == "earliest":
                    if USE_EPISODES:
                        ensure_episodes(self.db, start=parse.start, end=parse.end)
                        ear_rows = self.db.conn.execute(
                            """
                            SELECT id, start_time, end_time, process_name, dominant_title,
                                   capture_count, representative_text, representative_capture_id
                            FROM episodes
                            WHERE start_time BETWEEN ? AND ?
                            ORDER BY start_time ASC
                            LIMIT ?
                            """,
                            (parse.start, parse.end, top_k),
                        ).fetchall()
                        sources = []
                        for ep in ear_rows:
                            cids = [r[0] for r in self.db.conn.execute("SELECT capture_id FROM episode_captures WHERE episode_id = ? ORDER BY capture_id ASC", (ep["id"],)).fetchall()]
                            sources.append({
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
                            })
                    else:
                        ear_rows = self.db.conn.execute(
                            """
                            SELECT id, timestamp, source, text_content, window_title, process_name
                            FROM captures
                            WHERE timestamp BETWEEN ? AND ?
                            ORDER BY timestamp ASC
                            LIMIT ?
                            """,
                            (parse.start, parse.end, top_k),
                        ).fetchall()
                        sources = [dict(r) for r in ear_rows]

                    if sources:
                        first_c = sources[0]
                        title = first_c.get("dominant_title") or first_c.get("window_title")
                        cite = ""
                        if USE_GROUNDING:
                            cid = first_c.get("episode_id") or first_c.get("id")
                            tag = f"[E{cid}]" if first_c.get("source") == "episode" else f"[C{cid}]"
                            cite = f" {tag}"
                        structured_ans = (
                            f"The earliest activity recorded on {parse.start[:10]} started at {first_c['timestamp']} "
                            f"in window '{title}' ({first_c['process_name']}){cite}."
                        )

                search_time = (time.time() - search_start) * 1000

                # Build prompt using structured output as context, query LLM if available
                gen_start = time.time()
                prompt = (CONTEXT_TEMPLATE_GROUNDED if USE_GROUNDING else CONTEXT_TEMPLATE).format(
                    context_entries=structured_ans,
                    question=question,
                )
                answer = self._call_ollama(
                    prompt,
                    system_prompt=SYSTEM_PROMPT_GROUNDED if USE_GROUNDING else SYSTEM_PROMPT,
                )
                # If Ollama is unavailable or returns warning, return deterministic structured answer directly
                if answer.startswith("⚠️"):
                    answer = structured_ans

                grounding_rate = None
                partially_verified = False
                if USE_GROUNDING:
                    grounding_res = verify_grounding(
                        answer,
                        sources,
                        tolerance_minutes=CITATION_TOLERANCE_MINUTES,
                        min_grounding=GROUNDING_MIN,
                        is_refusal=False,
                    )
                    answer = grounding_res.verified_answer
                    grounding_rate = grounding_res.grounding_rate
                    partially_verified = grounding_res.partially_verified

                gen_time = (time.time() - gen_start) * 1000
                return {
                    "answer": answer,
                    "sources": sources,
                    "search_time_ms": search_time,
                    "generate_time_ms": gen_time,
                    "refused": False,
                    "refusal_reason": None,
                    "grounding_rate": grounding_rate,
                    "partially_verified": partially_verified,
                    "temporal_parse": parse.__dict__,
                    "answer_source": "aggregate_operator",
                    "ollama_stats": getattr(self, "last_ollama_stats", {}),
                }

            # 4. Standard Search with Time Filter & Residual Query
            search_start = time.time()
            time_range = (parse.start, parse.end) if (parse.start and parse.end) else None
            effective_query = parse.residual_query if parse.residual_query else question

            if effective_query.strip():
                query_embedding = self.embedder.generate(effective_query)
            else:
                query_embedding = None

            if USE_EPISODES:
                ensure_episodes(self.db, start=parse.start, end=parse.end)
                results = self.db.search_episodes(
                    query_embedding=query_embedding,
                    query_text=effective_query,
                    limit=top_k,
                    time_range=time_range,
                )
            else:
                results = self.db.search_hybrid(
                    effective_query,
                    query_embedding,
                    limit=top_k,
                    time_range=time_range,
                )
            search_time = (time.time() - search_start) * 1000

            # Pre-generation Refusal Gate (Chunk 3)
            if USE_GROUNDING:
                pre_refusal = check_pregeneration_refusals(
                    query=f"{question} {effective_query}",
                    db=self.db,
                    sources=results,
                    sim_floor=REFUSAL_SIM_FLOOR,
                    time_range=time_range,
                    residual_query=parse.residual_query if parse else None,
                )
                if pre_refusal:
                    return {
                        "answer": pre_refusal["answer"],
                        "sources": pre_refusal.get("sources", []),
                        "search_time_ms": search_time,
                        "generate_time_ms": 0,
                        "refused": True,
                        "refusal_reason": pre_refusal.get("refusal_reason"),
                        "grounding_rate": 1.0,
                        "partially_verified": False,
                        "temporal_parse": parse.__dict__,
                        "answer_source": "refusal_gate",
                        "ollama_stats": getattr(self, "last_ollama_stats", {}),
                    }

            if not results:
                return {
                    "answer": (
                        "I don't have any captured context matching that query in the specified time range. "
                        "Make sure the capture pipeline was running."
                    ),
                    "sources": [],
                    "search_time_ms": search_time,
                    "generate_time_ms": 0,
                    "refused": False,
                    "refusal_reason": None,
                    "grounding_rate": 0.0,
                    "partially_verified": False,
                    "temporal_parse": parse.__dict__,
                    "answer_source": "refusal_gate",
                    "ollama_stats": getattr(self, "last_ollama_stats", {}),
                }

            context_str = self._format_context(results)
            prompt = (CONTEXT_TEMPLATE_GROUNDED if USE_GROUNDING else CONTEXT_TEMPLATE).format(
                context_entries=context_str,
                question=question,
            )

            gen_start = time.time()
            answer = self._call_ollama(
                prompt,
                system_prompt=SYSTEM_PROMPT_GROUNDED if USE_GROUNDING else SYSTEM_PROMPT,
            )

            if answer.startswith("⚠️") and USE_GROUNDING:
                if not is_template_fallback_allowed():
                    raise RuntimeError(f"Ollama returned error: {answer} and ALLOW_TEMPLATE_FALLBACK is False.")
                answer = synthesize_grounded_answer(question, results, intent=parse.intent)
                answer_source = "template_fallback"
            elif answer.startswith("⚠️"):
                if not is_template_fallback_allowed():
                    raise RuntimeError(f"Ollama returned error: {answer} and ALLOW_TEMPLATE_FALLBACK is False.")
                answer_source = "template_fallback"
            else:
                answer_source = "llm"

            grounding_rate = None
            partially_verified = False
            if USE_GROUNDING:
                grounding_res = verify_grounding(
                    answer,
                    results,
                    tolerance_minutes=CITATION_TOLERANCE_MINUTES,
                    min_grounding=GROUNDING_MIN,
                    is_refusal=False,
                )
                if grounding_res.grounding_rate < GROUNDING_MIN and not answer.startswith("⚠️"):
                    stricter_prompt = prompt + "\n\nCRITICAL: Every claim MUST cite an episode ID (e.g. [E12]) and all timestamps mentioned must strictly match the cited episode."
                    answer2 = self._call_ollama(
                        stricter_prompt,
                        system_prompt=SYSTEM_PROMPT_GROUNDED,
                    )
                    if not answer2.startswith("⚠️"):
                        grounding_res2 = verify_grounding(
                            answer2,
                            results,
                            tolerance_minutes=CITATION_TOLERANCE_MINUTES,
                            min_grounding=GROUNDING_MIN,
                            is_refusal=False,
                        )
                        if grounding_res2.grounding_rate >= GROUNDING_MIN:
                            answer = answer2
                            grounding_res = grounding_res2

                answer = grounding_res.verified_answer
                grounding_rate = grounding_res.grounding_rate
                partially_verified = grounding_res.partially_verified

            gen_time = (time.time() - gen_start) * 1000

            return {
                "answer": answer,
                "sources": results,
                "search_time_ms": search_time,
                "generate_time_ms": gen_time,
                "refused": False,
                "refusal_reason": None,
                "grounding_rate": grounding_rate,
                "partially_verified": partially_verified,
                "temporal_parse": parse.__dict__,
                "answer_source": answer_source,
                "ollama_stats": getattr(self, "last_ollama_stats", {}),
            }

        # ─── Baseline Path (USE_TEMPORAL is False) ───────────────────
        query_embedding = self.embedder.generate(question)

        search_start = time.time()
        if USE_EPISODES:
            ensure_episodes(self.db)
            results = self.db.search_episodes(
                query_embedding=query_embedding,
                query_text=question,
                limit=top_k,
                time_range=None,
            )
        else:
            results = self.db.search_hybrid(question, query_embedding, limit=top_k)
        search_time = (time.time() - search_start) * 1000

        # Pre-generation Refusal Gate (Chunk 3)
        if USE_GROUNDING:
            pre_refusal = check_pregeneration_refusals(
                query=question,
                db=self.db,
                sources=results,
                sim_floor=REFUSAL_SIM_FLOOR,
                time_range=None,
                residual_query=None,
            )
            if pre_refusal:
                return {
                    "answer": pre_refusal["answer"],
                    "sources": pre_refusal.get("sources", []),
                    "search_time_ms": search_time,
                    "generate_time_ms": 0,
                    "refused": True,
                    "refusal_reason": pre_refusal.get("refusal_reason"),
                    "grounding_rate": 1.0,
                    "partially_verified": False,
                    "temporal_parse": None,
                    "answer_source": "refusal_gate",
                    "ollama_stats": getattr(self, "last_ollama_stats", {}),
                }

        if not results:
            return {
                "answer": "I don't have any captured context to answer that question. "
                          "Make sure the capture pipeline was running.",
                "sources": [],
                "search_time_ms": search_time,
                "generate_time_ms": 0,
                "refused": False,
                "refusal_reason": None,
                "grounding_rate": 0.0,
                "partially_verified": False,
                "temporal_parse": None,
                "answer_source": "refusal_gate",
                "ollama_stats": getattr(self, "last_ollama_stats", {}),
            }

        context_str = self._format_context(results)
        prompt = (CONTEXT_TEMPLATE_GROUNDED if USE_GROUNDING else CONTEXT_TEMPLATE).format(
            context_entries=context_str,
            question=question,
        )

        gen_start = time.time()
        answer = self._call_ollama(
            prompt,
            system_prompt=SYSTEM_PROMPT_GROUNDED if USE_GROUNDING else SYSTEM_PROMPT,
        )

        if answer.startswith("⚠️") and USE_GROUNDING:
            if not is_template_fallback_allowed():
                raise RuntimeError(f"Ollama returned error: {answer} and ALLOW_TEMPLATE_FALLBACK is False.")
            answer = synthesize_grounded_answer(question, results)
            answer_source = "template_fallback"
        elif answer.startswith("⚠️"):
            if not is_template_fallback_allowed():
                raise RuntimeError(f"Ollama returned error: {answer} and ALLOW_TEMPLATE_FALLBACK is False.")
            answer_source = "template_fallback"
        else:
            answer_source = "llm"

        grounding_rate = None
        partially_verified = False
        if USE_GROUNDING:
            grounding_res = verify_grounding(
                answer,
                results,
                tolerance_minutes=CITATION_TOLERANCE_MINUTES,
                min_grounding=GROUNDING_MIN,
                is_refusal=False,
            )
            if grounding_res.grounding_rate < GROUNDING_MIN and not answer.startswith("⚠️"):
                stricter_prompt = prompt + "\n\nCRITICAL: Every claim MUST cite an episode ID (e.g. [E12]) and all timestamps mentioned must strictly match the cited episode."
                answer2 = self._call_ollama(
                    stricter_prompt,
                    system_prompt=SYSTEM_PROMPT_GROUNDED,
                )
                if not answer2.startswith("⚠️"):
                    grounding_res2 = verify_grounding(
                        answer2,
                        results,
                        tolerance_minutes=CITATION_TOLERANCE_MINUTES,
                        min_grounding=GROUNDING_MIN,
                        is_refusal=False,
                    )
                    if grounding_res2.grounding_rate >= GROUNDING_MIN:
                        answer = answer2
                        grounding_res = grounding_res2

            answer = grounding_res.verified_answer
            grounding_rate = grounding_res.grounding_rate
            partially_verified = grounding_res.partially_verified

        gen_time = (time.time() - gen_start) * 1000

        return {
            "answer": answer,
            "sources": results,
            "search_time_ms": search_time,
            "generate_time_ms": gen_time,
            "refused": False,
            "refusal_reason": None,
            "grounding_rate": grounding_rate,
            "partially_verified": partially_verified,
            "temporal_parse": None,
            "answer_source": answer_source,
            "ollama_stats": getattr(self, "last_ollama_stats", {}),
        }

    def search_only(
        self, query_text: str, mode: str = "hybrid", top_k: int = SEARCH_TOP_K
    ) -> list[dict]:
        """
        Search without LLM generation. Useful for the `search` CLI command.

        Args:
            query_text: Search query
            mode: 'hybrid', 'semantic', or 'keyword'
            top_k: Number of results
        """
        query_embedding = self.embedder.generate(query_text)

        if mode == "semantic":
            return self.db.search_semantic(query_embedding, limit=top_k)
        elif mode == "keyword":
            return self.db.search_keyword(query_text, limit=top_k)
        else:
            return self.db.search_hybrid(query_text, query_embedding, limit=top_k)

    def _call_ollama(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        """Call the Ollama API to generate a response."""
        sys_prompt = system_prompt or SYSTEM_PROMPT
        active_model = model or self.get_model()
        self.last_ollama_stats = {}
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": active_model,
                    "prompt": prompt,
                    "system": sys_prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "top_p": 0.9,
                        "num_predict": 512,
                    },
                },
                timeout=(2.0, 60.0),
            )
            resp.raise_for_status()

            data = resp.json()
            self.last_ollama_stats = {
                "eval_count": data.get("eval_count", 0),
                "eval_duration": data.get("eval_duration", 0),
                "prompt_eval_duration": data.get("prompt_eval_duration", 0),
                "prompt_eval_count": data.get("prompt_eval_count", 0),
                "total_duration": data.get("total_duration", 0),
                "load_duration": data.get("load_duration", 0),
                "model": data.get("model", active_model),
            }
            return data.get("response", "").strip()

        except requests.ConnectionError:
            self.last_ollama_stats = {}
            if not is_template_fallback_allowed():
                raise RuntimeError(
                    f"Cannot connect to Ollama at {OLLAMA_BASE_URL} and ALLOW_TEMPLATE_FALLBACK is False. Aborting evaluation."
                )
            return (
                "⚠️  Cannot connect to Ollama. Make sure it's running: "
                "`ollama serve`"
            )
        except requests.Timeout:
            self.last_ollama_stats = {}
            if not is_template_fallback_allowed():
                raise RuntimeError("Ollama request timed out and ALLOW_TEMPLATE_FALLBACK is False. Aborting evaluation.")
            return "⚠️  Ollama request timed out. The model may be loading."
        except Exception as e:
            self.last_ollama_stats = {}
            if not is_template_fallback_allowed():
                raise RuntimeError(f"Ollama API error ({e}) and ALLOW_TEMPLATE_FALLBACK is False. Aborting evaluation.")
            logger.error(f"Ollama API error: {e}")
            return f"⚠️  Error generating answer: {e}"


# ─── Standalone Test ─────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("Testing RAG agent...")
    print("  (Requires Ollama running with llama3.2:3b pulled)")

    # Initialize components
    db = DatabaseManager()
    embedder = EmbeddingGenerator()
    rag = RAGAgent(db, embedder)

    # Insert some test data
    test_entries = [
        ("screen", "Working on the database schema for the ambient context engine",
         "schema.sql - VS Code", "Code.exe"),
        ("screen", "Reviewing Python documentation for threading module",
         "threading — Python docs - Chrome", "chrome.exe"),
        ("audio", "Let's discuss the project timeline and milestones for next week",
         None, None),
    ]

    for source, text, window, process in test_entries:
        emb = embedder.generate(text)
        db.insert_capture(
            source=source,
            text_content=text,
            embedding=emb,
            window_title=window,
            process_name=process,
        )

    print("  Inserted test data")

    # Test search
    results = rag.search_only("what was I coding?")
    print(f"\n  Search 'what was I coding?': {len(results)} results")
    for r in results:
        print(f"    [{r['source']}] {r['text_content'][:60]}...")

    # Test RAG query
    print("\n  Asking RAG: 'What was I working on today?'")
    response = rag.query("What was I working on today?")
    print(f"\n  Answer: {response['answer']}")
    print(f"  Search time: {response['search_time_ms']:.0f}ms")
    print(f"  Generate time: {response['generate_time_ms']:.0f}ms")

    db.close()
    print("\nRAG test complete!")
