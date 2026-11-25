"""
Intelligence Layer — Grounded Generation and Verification Gate (Chunk 3)

Provides:
1. Pre-generation refusal gates (future, empty-window, modality check, intent/motive hedge, similarity floor).
2. Inline citation formatting ([E12]) with episode time span and app.
3. Post-hoc verification checking citations and timestamp constraints.
4. Offline grounded synthesis fallback when LLM is unavailable.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as dtime
from typing import Any, Dict, List, Optional, Tuple, Set

from config import (
    CITATION_TOLERANCE_MINUTES,
    GROUNDING_MIN,
    REFUSAL_SIM_FLOOR,
)
from storage.db import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class GroundingResult:
    """Detailed result of post-hoc grounding verification."""
    grounding_rate: float
    total_sentences: int
    supported_sentences: int
    verified_answer: str
    partially_verified: bool
    sentence_details: List[Dict[str, Any]] = field(default_factory=list)


# ─── 1. Pre-Generation Refusal Gate ──────────────────────────────────

MODALITY_AUDIO_PATTERNS = [
    r"\b(?:on|during|in)\s+(?:the|a)\s+call\b",
    r"\bphone\s+call\b",
    r"\bzoom\s+call\b",
    r"\bmeeting\b",
    r"\b(?:what\s+did\s+.*?\s+say|colleague\s+say|someone\s+say|said\s+on\s+the|spoken\s+on)\b",
    r"\bvoice\s+call\b",
    r"\baudio\s+call\b",
]

MOTIVE_PATTERNS = [
    r"\bwhy\s+(?:was|did|am|were)\s+i\b",
    r"\breason\s+(?:for|why)\b",
    r"\bwhat\s+was\s+my\s+(?:reason|motive|intent|purpose)\b",
]

UNOBSERVABLE_EVENT_PATTERNS = [
    r"\bpower\s+(?:fluctuat\w*|cut|outage)\b",
    r"\bsecondary\s+screen\b",
    r"\bsecond\s+monitor\b",
    r"\bphysical\s+room\b",
    r"\bdesk\b",
    r"\bwebcam\b",
]


GENERIC_QUERY_WORDS = {
    "what", "was", "i", "doing", "working", "on", "active", "my", "activity",
    "activities", "worked", "did", "viewing", "looking", "at", "happening",
    "screen", "tasks", "task", "history", "context", "up", "to", "the", "a", "an",
    "in", "of", "for", "and", "or", "me", "show", "tell", "summarize", "list"
}


def is_generic_or_empty_query(query: Optional[str]) -> bool:
    """Return True if the query is empty, whitespace, or contains only generic stop words."""
    if not query or not query.strip():
        return True
    words = re.findall(r"\b\w+\b", query.lower())
    substantive = [w for w in words if w not in GENERIC_QUERY_WORDS]
    return len(substantive) == 0


def check_pregeneration_refusals(
    query: str,
    db: DatabaseManager,
    sources: List[Dict[str, Any]],
    sim_floor: float = REFUSAL_SIM_FLOOR,
    time_range: Optional[Tuple[str, str]] = None,
    residual_query: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Check pre-generation refusal gates before calling the LLM:
    (b) Similarity floor — top episode cosine to residual query < REFUSAL_SIM_FLOOR and no keyword hits
        (skipped if residual query is empty or generic, e.g. "what was I doing")
    (c) Modality check — query refers to a call/meeting/speech and 0 audio captures exist
    (d) Motive/intent questions — return hedged answer stating on-screen facts but refusing internal motive
    (e) Unobservable physical events (secondary screen, power fluctuation).

    Returns a refusal dict if any gate fires, else None.
    """
    clean_q = query.lower()

    # Gate (c): Modality check (Audio / Calls)
    for pat in MODALITY_AUDIO_PATTERNS:
        if re.search(pat, clean_q, re.IGNORECASE):
            # Check if database has any audio captures in the range (or overall)
            cur = db.conn.cursor()
            if time_range and time_range[0] and time_range[1]:
                audio_count = cur.execute(
                    "SELECT COUNT(*) FROM captures WHERE source = 'audio' AND timestamp BETWEEN ? AND ?",
                    (time_range[0], time_range[1]),
                ).fetchone()[0]
            else:
                audio_count = cur.execute(
                    "SELECT COUNT(*) FROM captures WHERE source = 'audio'"
                ).fetchone()[0]

            if audio_count == 0:
                return {
                    "answer": (
                        "I cannot answer that question because no audio transcripts or call recordings "
                        "were captured for that period. Screen monitoring does not record audio calls."
                    ),
                    "sources": [],
                    "refused": True,
                    "refusal_reason": "modality_unsupported_no_audio",
                }

    # Gate (e): Unobservable physical events (e.g. power fluctuation, secondary uncaptured screen)
    for pat in UNOBSERVABLE_EVENT_PATTERNS:
        if re.search(pat, clean_q, re.IGNORECASE):
            return {
                "answer": (
                    "I cannot answer that question because external physical events (such as power fluctuations) "
                    "and uncaptured secondary displays are unobservable by the ambient context engine."
                ),
                "sources": [],
                "refused": True,
                "refusal_reason": "unobservable_physical_event",
            }

    # Gate (d): Motive / Intent check ("Why was I...")
    for pat in MOTIVE_PATTERNS:
        if re.search(pat, clean_q, re.IGNORECASE):
            # Return hedged answer with retrieved screen state, flagged as refusal
            if sources:
                top_s = sources[0]
                title = top_s.get("dominant_title") or top_s.get("window_title") or "Unknown"
                proc = top_s.get("process_name") or "active application"
                t_str = top_s.get("start_time") or top_s.get("timestamp") or "that time"
                cid_label = f"[E{top_s['id']}]" if top_s.get("source") == "episode" else f"[C{top_s['id']}]"
                hedged_answer = (
                    f"Screen captures show that at {t_str}, you were actively viewing '{title}' ({proc}) {cid_label}. "
                    f"However, user motivation, reasoning, or intent cannot be determined from screen captures alone."
                )
            else:
                hedged_answer = (
                    "I cannot determine the reason or motivation for your activity, "
                    "as user intent cannot be inferred from screen captures."
                )
            return {
                "answer": hedged_answer,
                "sources": sources,
                "refused": True,
                "refusal_reason": "unobservable_internal_intent",
            }

    # Gate (b): Similarity floor check
    # Skip similarity floor when residual query is empty or generic
    if residual_query is not None and is_generic_or_empty_query(residual_query):
        pass  # Skip floor check: temporal constraints define relevance
    elif sources:
        top_s = sources[0]
        top_cos = top_s.get("cosine_sim", 0.0)
        has_any_kw = any(s.get("keyword_match", False) for s in sources)
        if top_cos < sim_floor and not has_any_kw:
            return {
                "answer": (
                    "I could not find sufficient evidence or context in your activity history to answer that question "
                    f"(top match cosine similarity {top_cos:.2f} is below the required floor of {sim_floor:.2f} and keyword search returned nothing)."
                ),
                "sources": [],
                "refused": True,
                "refusal_reason": "low_confidence_similarity",
            }

    return None


# ─── 2. Citation Extraction & Post-hoc Verifier ──────────────────────

def split_sentences(text: str) -> List[str]:
    """Split text into sentences while respecting abbreviations and timestamps."""
    # Split by standard sentence terminators followed by space or newline
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    cleaned = []
    for s in raw_sentences:
        s_str = s.strip()
        if s_str and not s_str.startswith("⚠️"):
            cleaned.append(s_str)
    return cleaned


def extract_citations(sentence: str) -> Set[int]:
    """Extract citation IDs in format [E12], [C15], or [12]."""
    matches = re.findall(r"\[(?:E|C)?(\d+)\]", sentence, re.IGNORECASE)
    return {int(m) for m in matches}


def parse_sentence_times(sentence: str) -> List[dtime]:
    """Extract clock times mentioned in a sentence (e.g. 9:50 PM, 21:45, 950 PM)."""
    times = []
    # Match patterns like: 9:50 PM, 9:50pm, 21:50, 950 PM
    time_pats = [
        r"\b(\d{1,2}):(\d{2})(?::\d{2})?\s*(am|pm)?\b",
        r"\b(\d{1,2})(\d{2})\s*(am|pm)\b",
    ]
    for pat in time_pats:
        for m in re.finditer(pat, sentence, re.IGNORECASE):
            h_str, m_str = m.group(1), m.group(2)
            meridiem = m.group(3).lower() if m.lastindex >= 3 and m.group(3) else None
            try:
                h = int(h_str)
                minute = int(m_str)
                if meridiem == "pm" and h < 12:
                    h += 12
                elif meridiem == "am" and h == 12:
                    h = 0
                if 0 <= h <= 23 and 0 <= minute <= 59:
                    times.append(dtime(h, minute))
            except ValueError:
                continue
    return times


def verify_grounding(
    answer: str,
    sources: List[Dict[str, Any]],
    tolerance_minutes: int = CITATION_TOLERANCE_MINUTES,
    min_grounding: float = GROUNDING_MIN,
    is_refusal: bool = False,
) -> GroundingResult:
    """
    Verify whether every claim in the answer is grounded in retrieved sources:
    - Each sentence must carry >= 1 citation matching a retrieved source.
    - Any timestamps in the sentence must fall inside the cited source's interval (+/- tolerance).

    Returns GroundingResult with grounding_rate and filtered answer if below min_grounding.
    """
    if is_refusal:
        return GroundingResult(
            grounding_rate=1.0,
            total_sentences=1,
            supported_sentences=1,
            verified_answer=answer,
            partially_verified=False,
            sentence_details=[{"sentence": answer, "supported": True, "reason": "refusal_response"}],
        )

    sentences = split_sentences(answer)
    if not sentences:
        return GroundingResult(
            grounding_rate=0.0,
            total_sentences=0,
            supported_sentences=0,
            verified_answer=answer,
            partially_verified=False,
            sentence_details=[],
        )

    # Build source intervals lookup: id -> (start_dt, end_dt)
    source_intervals: Dict[int, Tuple[datetime, datetime]] = {}
    for s in sources:
        sid = s.get("episode_id") or s.get("id")
        start_str = s.get("start_time") or s.get("timestamp")
        end_str = s.get("end_time") or s.get("timestamp")
        if sid is not None and start_str:
            try:
                s_dt = datetime.fromisoformat(start_str)
                e_dt = datetime.fromisoformat(end_str) if end_str else s_dt
                source_intervals[sid] = (s_dt, e_dt)
            except (ValueError, TypeError):
                continue

    valid_sids = set(source_intervals.keys())
    tol_delta = timedelta(minutes=tolerance_minutes)

    supported_count = 0
    sentence_details = []
    supported_sentences_list = []

    for s_text in sentences:
        c_ids = extract_citations(s_text)
        matching_cids = c_ids.intersection(valid_sids)

        if not matching_cids:
            sentence_details.append({
                "sentence": s_text,
                "supported": False,
                "citations": list(c_ids),
                "reason": "missing_or_invalid_citation",
            })
            continue

        # Check timestamp consistency
        s_times = parse_sentence_times(s_text)
        time_valid = True
        if s_times:
            # Check if mentioned time falls within any cited source's interval
            time_match = False
            for cid in matching_cids:
                s_dt, e_dt = source_intervals[cid]
                for st in s_times:
                    target_dt = datetime.combine(s_dt.date(), st)
                    if (s_dt - tol_delta) <= target_dt <= (e_dt + tol_delta):
                        time_match = True
                        break
                if time_match:
                    break
            time_valid = time_match

        if time_valid:
            supported_count += 1
            supported_sentences_list.append(s_text)
            sentence_details.append({
                "sentence": s_text,
                "supported": True,
                "citations": list(matching_cids),
                "reason": "verified_citation_and_timestamp",
            })
        else:
            sentence_details.append({
                "sentence": s_text,
                "supported": False,
                "citations": list(matching_cids),
                "reason": "timestamp_outside_cited_interval",
            })

    grounding_rate = supported_count / len(sentences)
    partially_verified = False
    verified_answer = answer

    if grounding_rate < min_grounding:
        partially_verified = True
        if supported_sentences_list:
            verified_answer = " ".join(supported_sentences_list) + " [Partially verified from context]"
        else:
            verified_answer = (
                "Context was retrieved, but claims could not be verified against the citation timestamps."
            )

    return GroundingResult(
        grounding_rate=round(grounding_rate, 4),
        total_sentences=len(sentences),
        supported_sentences=supported_count,
        verified_answer=verified_answer,
        partially_verified=partially_verified,
        sentence_details=sentence_details,
    )


# ─── 3. Offline Grounded Synthesis Fallback ──────────────────────────

def synthesize_grounded_answer(
    question: str,
    sources: List[Dict[str, Any]],
    intent: str = "search",
) -> str:
    """
    Produce a clean, strictly cited grounded answer from retrieved episodes
    when Ollama / external LLM is offline.
    """
    if not sources:
        return "I don't have any captured context matching that query."

    # Format claims with inline [E{id}] citations
    claims = []
    seen_titles = set()

    for r in sources[:5]:
        ep_id = r.get("episode_id") or r.get("id")
        tag = f"[E{ep_id}]" if r.get("source") == "episode" else f"[C{ep_id}]"
        proc = r.get("process_name") or "Unknown application"
        title = r.get("dominant_title") or r.get("window_title") or "workspace"
        start_ts = r.get("start_time") or r.get("timestamp") or ""
        end_ts = r.get("end_time") or r.get("timestamp") or ""

        # Format human readable time
        t_label = start_ts[11:16] if len(start_ts) >= 16 else start_ts

        key = (proc, title)
        if key not in seen_titles:
            seen_titles.add(key)
            claims.append(f"At {t_label}, you were working in {proc} on '{title}' {tag}.")

    if not claims:
        top_r = sources[0]
        ep_id = top_r.get("episode_id") or top_r.get("id")
        tag = f"[E{ep_id}]"
        return f"Activity recorded at {top_r.get('timestamp')} was in {top_r.get('process_name')} {tag}."

    return " ".join(claims)
