#!/usr/bin/env python3
"""
Evaluation Runner — evaluation/run_eval.py

Evaluates the OmniContext RAGAgent against an evaluation query set.
Loads a frozen SQLite database snapshot, reads queries and ground truth from
queries.json, runs each query through RAGAgent.query unchanged, and calculates:
- temporal_precision: % of retrieved captures within expected time window
- precision@k: % of top-k retrieved captures that match ground-truth relevant IDs
- grounding_rate: % of factual claims/sentences in generated answer grounded in retrieved context
- refusal_recall: % of queries with should_refuse=True correctly refused
- false_refusal_rate: % of queries with should_refuse=False erroneously refused

Outputs:
- JSON results file to evaluation/results/
- Markdown summary table and Delta table to evaluation/results/
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Set offline mode for local cached models (prevents 180s network retry hang)
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import DatabaseManager
from processing.embed import EmbeddingGenerator
from intelligence.rag import RAGAgent

# Suppress overly verbose library loggers during eval
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("eval_runner")
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


# Common phrases indicating that the model/system refused or expressed insufficiency of context
REFUSAL_INDICATORS = [
    "don't have enough context",
    "do not have enough context",
    "don't have enough information",
    "do not have enough information",
    "don't have any captured context",
    "do not have any captured context",
    "not enough context",
    "not enough information",
    "insufficient context",
    "insufficient information",
    "cannot determine",
    "unable to determine",
    "cannot confirm",
    "unable to confirm",
    "cannot find",
    "unable to find",
    "no record",
    "no captured activity",
    "no captured context",
    "no context",
    "cannot answer",
    "unable to answer",
    "outside the",
    "not available",
    "no evidence",
    "not mentioned in the context",
    "cannot predict",
    "unable to predict",
    "i cannot tell",
    "i am unable to tell",
]


def is_refusal_response(answer: str, sources: List[Dict[str, Any]], rag_refused: Optional[bool] = None) -> bool:
    """Determine whether the response represents a refusal or declaration of insufficient context."""
    if rag_refused is True:
        return True

    if not sources:
        # Default RAG answer when 0 sources are retrieved
        return True

    clean_ans = answer.strip().lower()

    # If the answer is an error message (like Ollama connection failure), it's not a grounded refusal
    if clean_ans.startswith("⚠️"):
        return False

    for phrase in REFUSAL_INDICATORS:
        if phrase in clean_ans:
            return True

    return False


def is_connection_error(answer: str) -> bool:
    """Check if the answer was an Ollama connection error rather than LLM text."""
    return answer.strip().startswith("⚠️")


def compute_temporal_precision(
    sources: List[Dict[str, Any]],
    expected_window: Optional[Dict[str, str]],
    should_refuse: bool,
) -> Optional[float]:
    """
    Compute temporal precision: % of retrieved sources within expected time window.
    Supports both point-in-time captures and interval-based episodes.
    Returns None if expected_window is not specified (e.g. Pure Semantic queries).
    """
    if not expected_window or "start" not in expected_window or "end" not in expected_window:
        return None

    if not sources:
        return 1.0 if should_refuse else 0.0

    try:
        start_dt = datetime.fromisoformat(expected_window["start"])
        end_dt = datetime.fromisoformat(expected_window["end"])
    except (ValueError, TypeError):
        return None

    in_window_count = 0
    for s in sources:
        start_str = s.get("start_time") or s.get("timestamp")
        end_str = s.get("end_time") or s.get("timestamp")
        if not start_str:
            continue
        try:
            s_dt = datetime.fromisoformat(start_str)
            e_dt = datetime.fromisoformat(end_str) if end_str else s_dt
            # Overlaps the expected window
            if s_dt <= end_dt and e_dt >= start_dt:
                in_window_count += 1
        except (ValueError, TypeError):
            continue

    return in_window_count / len(sources)


def compute_precision_at_k(
    sources: List[Dict[str, Any]],
    relevant_ids: List[int],
    k: int,
    should_refuse: bool,
) -> Optional[float]:
    """
    Compute Precision@k: fraction of top-k retrieved sources that match relevant_ids.
    For episodes (Chunk 2), an episode is relevant if it contains ANY ground-truth capture ID.
    If relevant_ids is empty and should_refuse is True:
        Returns 1.0 if 0 sources retrieved, 0.0 otherwise.
    """
    top_k_sources = sources[:k]
    rel_set = set(relevant_ids)

    if not rel_set:
        if should_refuse:
            return 1.0 if len(top_k_sources) == 0 else 0.0
        return None

    if not top_k_sources:
        return 0.0

    hits = 0
    for s in top_k_sources:
        cap_ids = s.get("capture_ids")
        if cap_ids:
            if (
                any(cid in rel_set for cid in cap_ids)
                or s.get("id") in rel_set
                or s.get("representative_capture_id") in rel_set
            ):
                hits += 1
        else:
            if s.get("id") in rel_set:
                hits += 1

    return hits / len(top_k_sources)


def compute_grounding_rate(
    answer: str,
    sources: List[Dict[str, Any]],
    should_refuse: bool,
    is_refusal: bool,
    rag_grounding_rate: Optional[float] = None,
) -> float:
    """
    Compute grounding rate:
    - If refusal query and system correctly refused: 1.0
    - If rag_grounding_rate is explicitly returned by RAGAgent verifier: use that rate
    - If Ollama was unavailable or answer is empty: 0.0
    - Otherwise: fraction of sentences supported by citations ([E12], [C5], [12]), timestamps, window titles, or source text.
    """
    if should_refuse and is_refusal:
        return 1.0

    if rag_grounding_rate is not None:
        return rag_grounding_rate

    if is_connection_error(answer):
        return 0.0

    if not sources or not answer.strip():
        return 0.0

    # Build reference tokens/phrases from retrieved sources
    window_titles = [
        s["window_title"].lower()
        for s in sources
        if s.get("window_title")
    ]
    process_names = [
        s["process_name"].lower().replace(".exe", "")
        for s in sources
        if s.get("process_name")
    ]

    time_tokens = set()
    for s in sources:
        ts = s.get("timestamp", "")
        if "T" in ts:
            date_part, time_part = ts.split("T", 1)
            time_tokens.add(date_part)
            time_tokens.add(time_part[:5])

    raw_sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", answer)
        if s.strip() and not s.startswith("⚠️")
    ]

    if not raw_sentences:
        return 0.0

    grounded_count = 0
    for sentence in raw_sentences:
        s_lower = sentence.lower()
        is_grounded = False

        if re.search(r"\[(?:E|C)?\d+\]", sentence):
            is_grounded = True

        if not is_grounded:
            for tt in time_tokens:
                if tt in sentence or tt.replace("-", "/") in sentence:
                    is_grounded = True
                    break

        if not is_grounded:
            for wt in window_titles:
                significant_words = [w for w in re.findall(r"\w+", wt) if len(w) > 3]
                if any(w in s_lower for w in significant_words):
                    is_grounded = True
                    break

        if not is_grounded:
            for pn in process_names:
                if pn and pn in s_lower:
                    is_grounded = True
                    break

        if not is_grounded:
            words = re.findall(r"\w+", s_lower)
            if len(words) >= 4:
                trigrams = [" ".join(words[idx:idx+3]) for idx in range(len(words)-2)]
                for src in sources:
                    src_txt = src.get("text_content", "").lower()
                    if any(tg in src_txt for tg in trigrams):
                        is_grounded = True
                        break

        if is_grounded:
            grounded_count += 1

    return grounded_count / len(raw_sentences)


def load_queries(queries_path: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Load query definitions and reference_now from JSON file."""
    with open(queries_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    reference_now = data.get("reference_now") if isinstance(data, dict) else None
    flat_queries = []

    if isinstance(data, list):
        flat_queries = data
    elif isinstance(data, dict):
        if "queries" in data and isinstance(data["queries"], list):
            flat_queries = data["queries"]
        elif "categories" in data and isinstance(data["categories"], list):
            for cat in data["categories"]:
                cat_id = cat.get("id", "unknown")
                for q in cat.get("queries", []):
                    q_copy = dict(q)
                    if "category" not in q_copy:
                        q_copy["category"] = cat_id
                    flat_queries.append(q_copy)

    standardized = []
    for idx, q in enumerate(flat_queries, start=1):
        q_id = q.get("id", f"Q{idx}")
        category = q.get("category", "unknown")
        query_text = q.get("query") or q.get("query_text") or q.get("text") or q.get("template")

        gt = q.get("ground_truth") or {}
        rel_ids = gt.get("relevant_capture_ids")
        if rel_ids is None and "relevant_capture_ids" in q:
            rel_ids = q["relevant_capture_ids"]
        rel_ids = rel_ids or []

        time_window = gt.get("expected_time_window")
        if time_window is None and "expected_time_window" in q:
            time_window = q["expected_time_window"]

        should_refuse = gt.get("should_refuse")
        if should_refuse is None and "should_refuse" in q:
            should_refuse = q["should_refuse"]
        should_refuse = bool(should_refuse)

        standardized.append({
            "id": q_id,
            "category": category,
            "query": query_text,
            "ground_truth": {
                "relevant_capture_ids": rel_ids,
                "expected_time_window": time_window,
                "should_refuse": should_refuse,
                "expected_answer": gt.get("expected_answer", ""),
            }
        })

    return standardized, reference_now


def run_evaluation(
    db_path: Path,
    queries_path: Path,
    output_dir: Path,
    k: int = 5,
    tag: str = "baseline",
    compare_tag: Optional[str] = None,
) -> Tuple[Dict[str, Any], Path, Path]:
    """Execute evaluation run across all queries, compute metrics, and write outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info(f"Opening database snapshot: {db_path}")
    if not db_path.exists():
        raise FileNotFoundError(f"Database snapshot not found at: {db_path}")

    queries, reference_now = load_queries(queries_path)
    logger.info(f"Loaded {len(queries)} evaluation queries from {queries_path}")
    if reference_now:
        logger.info(f"Using fixed reference_now: {reference_now}")

    logger.info("Initializing DatabaseManager and EmbeddingGenerator...")
    db = DatabaseManager(db_path=db_path)
    embedder = EmbeddingGenerator()
    rag = RAGAgent(db=db, embedder=embedder)

    query_results = []

    print("\n" + "=" * 75)
    print(f"  OmniContext Evaluation Run: {tag.upper()}")
    print(f"  DB Snapshot: {db_path.name} | Total Queries: {len(queries)}")
    if reference_now:
        print(f"  Reference Now: {reference_now}")
    print("=" * 75 + "\n")

    for i, q in enumerate(queries, start=1):
        q_id = q["id"]
        cat = q["category"]
        q_text = q["query"]
        gt = q["ground_truth"]
        should_refuse = gt["should_refuse"]
        expected_window = gt["expected_time_window"]
        relevant_ids = gt["relevant_capture_ids"]

        print(f"[{i:02d}/{len(queries):02d}] ({cat.upper()}) {q_id}: {q_text}")

        # Run query through RAGAgent
        start_time = time.time()
        try:
            rag_output = rag.query(q_text, reference_now=reference_now)
        except Exception as query_err:
            logger.warning(f"Error querying RAGAgent for {q_id}: {query_err}")
            rag_output = {
                "answer": f"⚠️ Error executing query: {query_err}",
                "sources": [],
                "search_time_ms": 0,
                "generate_time_ms": 0,
                "refused": False,
                "refusal_reason": None,
            }
        total_eval_time = (time.time() - start_time) * 1000

        answer = rag_output.get("answer", "")
        sources = rag_output.get("sources", [])
        retrieved_ids = [s.get("id") for s in sources]
        rag_refused = rag_output.get("refused", False)

        # Metric evaluations
        is_refusal = is_refusal_response(answer, sources, rag_refused=rag_refused)
        t_prec = compute_temporal_precision(sources, expected_window, should_refuse)
        p_at_k = compute_precision_at_k(sources, relevant_ids, k, should_refuse)
        grounding = compute_grounding_rate(
            answer,
            sources,
            should_refuse,
            is_refusal,
            rag_grounding_rate=rag_output.get("grounding_rate"),
        )

        top_k_srcs = sources[:k]
        d_eps = len(set(s.get("episode_id", s.get("id")) for s in top_k_srcs))
        c_chars = sum(len(s.get("text_content") or s.get("representative_text") or "") for s in top_k_srcs)

        # Dual refusal metrics:
        # 1. Was it a should_refuse query that was correctly refused? (Recall)
        # 2. Was it a non-refuse query that was falsely refused? (False Refusal)
        correctly_refused = (is_refusal if should_refuse else None)
        falsely_refused = (is_refusal if not should_refuse else None)

        query_record = {
            "id": q_id,
            "category": cat,
            "query": q_text,
            "ground_truth": gt,
            "execution": {
                "search_time_ms": rag_output.get("search_time_ms", 0),
                "generate_time_ms": rag_output.get("generate_time_ms", 0),
                "total_time_ms": total_eval_time,
                "retrieved_count": len(sources),
                "retrieved_ids": retrieved_ids[:k],
                "distinct_episodes": d_eps,
                "context_chars": c_chars,
                "is_refusal": is_refusal,
                "refusal_reason": rag_output.get("refusal_reason"),
            },
            "metrics": {
                "temporal_precision": round(t_prec, 4) if t_prec is not None else None,
                "precision_at_k": round(p_at_k, 4) if p_at_k is not None else None,
                "grounding_rate": round(grounding, 4),
                "correctly_refused": correctly_refused,
                "falsely_refused": falsely_refused,
            },
            "answer": answer,
            "sources": sources[:k],
        }
        query_results.append(query_record)

        print(
            f"      -> Sources: {len(sources)} | "
            f"P@{k}: {f'{p_at_k:.2f}' if p_at_k is not None else 'N/A'} | "
            f"TempPrec: {f'{t_prec:.2f}' if t_prec is not None else 'N/A'} | "
            f"Grounding: {grounding:.2f} | "
            f"Refused: {'Yes' if is_refusal else 'No'} (Expected: {'Yes' if should_refuse else 'No'})"
        )

    # Calculate per-category and overall statistics
    categories = sorted(list(set(q["category"] for q in query_results)))
    cat_summary = {}

    for cat in categories:
        cat_qs = [q for q in query_results if q["category"] == cat]
        t_precs = [q["metrics"]["temporal_precision"] for q in cat_qs if q["metrics"]["temporal_precision"] is not None]
        p_at_ks = [q["metrics"]["precision_at_k"] for q in cat_qs if q["metrics"]["precision_at_k"] is not None]
        groundings = [q["metrics"]["grounding_rate"] for q in cat_qs]

        refuse_qs = [q for q in cat_qs if q["ground_truth"]["should_refuse"]]
        refuse_hits = sum(1 for q in refuse_qs if q["execution"]["is_refusal"])

        non_refuse_qs = [q for q in cat_qs if not q["ground_truth"]["should_refuse"]]
        false_refuse_hits = sum(1 for q in non_refuse_qs if q["execution"]["is_refusal"])

        cat_summary[cat] = {
            "query_count": len(cat_qs),
            "temporal_precision": round(sum(t_precs) / len(t_precs), 4) if t_precs else None,
            "temporal_precision_count": f"{len(t_precs)}/{len(cat_qs)}",
            "precision_at_k": round(sum(p_at_ks) / len(p_at_ks), 4) if p_at_ks else None,
            "precision_at_k_count": f"{len(p_at_ks)}/{len(cat_qs)}",
            "grounding_rate": round(sum(groundings) / len(groundings), 4) if groundings else 0.0,
            "grounding_rate_count": f"{len(groundings)}/{len(cat_qs)}",
            "refusal_recall": round(refuse_hits / len(refuse_qs), 4) if refuse_qs else None,
            "refusal_recall_count": f"{refuse_hits}/{len(refuse_qs)}" if refuse_qs else "N/A",
            "false_refusal_rate": round(false_refuse_hits / len(non_refuse_qs), 4) if non_refuse_qs else None,
            "false_refusal_count": f"{false_refuse_hits}/{len(non_refuse_qs)}" if non_refuse_qs else "N/A",
        }

    all_t_precs = [q["metrics"]["temporal_precision"] for q in query_results if q["metrics"]["temporal_precision"] is not None]
    all_p_at_ks = [q["metrics"]["precision_at_k"] for q in query_results if q["metrics"]["precision_at_k"] is not None]
    all_groundings = [q["metrics"]["grounding_rate"] for q in query_results]

    all_refuse_qs = [q for q in query_results if q["ground_truth"]["should_refuse"]]
    all_refuse_hits = sum(1 for q in all_refuse_qs if q["execution"]["is_refusal"])

    all_non_refuse_qs = [q for q in query_results if not q["ground_truth"]["should_refuse"]]
    all_false_refuse_hits = sum(1 for q in all_non_refuse_qs if q["execution"]["is_refusal"])

    # Chunk 2 Episode & Efficiency metrics
    total_caps_in_db = db.conn.execute("SELECT count(*) FROM captures").fetchone()[0]
    total_eps_in_db = db.conn.execute("SELECT count(*) FROM episodes").fetchone()[0]
    db_compression_ratio = round(total_caps_in_db / total_eps_in_db, 2) if total_eps_in_db > 0 else 1.0

    distinct_eps_list = [q["execution"].get("distinct_episodes", 1) for q in query_results]
    context_chars_list = [q["execution"].get("context_chars", 0) for q in query_results]
    gen_lat_list = [q["execution"].get("total_time_ms", 0.0) for q in query_results]

    overall_summary = {
        "total_queries": len(query_results),
        "temporal_precision": round(sum(all_t_precs) / len(all_t_precs), 4) if all_t_precs else None,
        "temporal_precision_count": f"{len(all_t_precs)}/{len(query_results)}",
        "precision_at_k": round(sum(all_p_at_ks) / len(all_p_at_ks), 4) if all_p_at_ks else None,
        "precision_at_k_count": f"{len(all_p_at_ks)}/{len(query_results)}",
        "grounding_rate": round(sum(all_groundings) / len(all_groundings), 4) if all_groundings else 0.0,
        "grounding_rate_count": f"{len(all_groundings)}/{len(query_results)}",
        "refusal_recall": round(all_refuse_hits / len(all_refuse_qs), 4) if all_refuse_qs else None,
        "refusal_recall_count": f"{all_refuse_hits}/{len(all_refuse_qs)}",
        "false_refusal_rate": round(all_false_refuse_hits / len(all_non_refuse_qs), 4) if all_non_refuse_qs else None,
        "false_refusal_count": f"{all_false_refuse_hits}/{len(all_non_refuse_qs)}",
        "compression_ratio": db_compression_ratio,
        "distinct_episodes_at_k": round(sum(distinct_eps_list) / len(distinct_eps_list), 2) if distinct_eps_list else 0.0,
        "mean_context_chars": round(sum(context_chars_list) / len(context_chars_list), 1) if context_chars_list else 0.0,
        "mean_generation_latency_ms": round(sum(gen_lat_list) / len(gen_lat_list), 1) if gen_lat_list else 0.0,
    }

    full_results = {
        "metadata": {
            "tag": tag,
            "timestamp": timestamp_str,
            "db_path": str(db_path.resolve()),
            "queries_path": str(queries_path.resolve()),
            "reference_now": reference_now,
            "k": k,
        },
        "overall": overall_summary,
        "by_category": cat_summary,
        "queries": query_results,
    }

    # Load baseline for delta comparison if available
    baseline_data = None
    if compare_tag:
        target_compare = compare_tag
    elif tag == "grounded":
        target_compare = "episodes" if (output_dir / "episodes_results.json").exists() else "temporal"
    elif tag == "episodes":
        target_compare = "temporal" if (output_dir / "temporal_results.json").exists() else "baseline"
    else:
        target_compare = "baseline" if tag != "baseline" else None
    if target_compare:
        base_file = output_dir / f"{target_compare}_results.json"
        if base_file.exists():
            try:
                with open(base_file, "r", encoding="utf-8") as bf:
                    baseline_data = json.load(bf)
                logger.info(f"Loaded {target_compare} results for delta comparison from {base_file}")
            except Exception as be:
                logger.warning(f"Could not load comparison file {base_file}: {be}")

    # Generate Markdown report with delta table
    md_content = generate_markdown_summary(full_results, baseline_data=baseline_data, compare_tag=target_compare)

    # Write JSON results
    json_path = output_dir / f"{tag}_results.json"
    timestamped_json_path = output_dir / f"eval_results_{timestamp_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2)
    with open(timestamped_json_path, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2)

    # Write Markdown summary
    md_path = output_dir / f"{tag}_summary.md"
    timestamped_md_path = output_dir / f"eval_summary_{timestamp_str}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    with open(timestamped_md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print("\n" + "=" * 75)
    print("  EVALUATION SUMMARY")
    print("=" * 75)
    print(md_content)
    print(f"\nResults saved to:")
    print(f"  • JSON:     {json_path}")
    print(f"  • Markdown: {md_path}")
    print("=" * 75 + "\n")

    db.close()
    return full_results, json_path, md_path


def generate_markdown_summary(
    results: Dict[str, Any],
    baseline_data: Optional[Dict[str, Any]] = None,
    compare_tag: Optional[str] = None,
) -> str:
    """Format evaluation metrics into a clean GitHub-flavored markdown report."""
    meta = results["metadata"]
    by_cat = results["by_category"]
    overall = results["overall"]
    tag = meta["tag"]

    def fmt_stat(val: Optional[float], count_str: Optional[str] = None) -> str:
        if val is None:
            return "N/A"
        pct = f"{val * 100:.1f}%"
        if count_str and count_str != "N/A":
            return f"{pct} ({count_str})"
        return pct

    def fmt_delta(curr: Optional[float], base: Optional[float]) -> str:
        if curr is None or base is None:
            return "—"
        diff = (curr - base) * 100
        sign = "+" if diff > 0 else ""
        return f"{sign}{diff:.1f}%"

    lines = [
        f"# OmniContext Evaluation Results — Tag: `{tag}`",
        f"",
        f"- **Run Tag:** `{tag}`",
        f"- **Timestamp:** `{meta['timestamp']}`",
        f"- **Database Snapshot:** `{meta['db_path']}`",
        f"- **Reference Now:** `{meta.get('reference_now', 'N/A')}`",
        f"- **Queries Evaluated:** {overall['total_queries']}",
        f"- **Evaluation Metric Top-K:** {meta['k']}",
        f"",
        f"## Summary Table per Category",
        f"",
        f"| Category | Queries | Temporal Precision | Precision@{meta['k']} | Grounding Rate | Refusal Recall (Should Refuse) | False Refusal Rate (Non-Refuse) |",
        f"|---|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]

    for cat_id, cat_data in by_cat.items():
        cat_name = cat_id.capitalize()
        tp_str = fmt_stat(cat_data["temporal_precision"], cat_data["temporal_precision_count"])
        pk_str = fmt_stat(cat_data["precision_at_k"], cat_data["precision_at_k_count"])
        gr_str = fmt_stat(cat_data["grounding_rate"], cat_data["grounding_rate_count"])
        rr_str = fmt_stat(cat_data.get("refusal_recall"), cat_data.get("refusal_recall_count"))
        fr_str = fmt_stat(cat_data.get("false_refusal_rate"), cat_data.get("false_refusal_count"))
        lines.append(
            f"| **{cat_name}** | {cat_data['query_count']} | {tp_str} | {pk_str} | {gr_str} | {rr_str} | {fr_str} |"
        )

    # Overall row
    lines.extend([
        f"| **Overall** | **{overall['total_queries']}** | **{fmt_stat(overall['temporal_precision'], overall['temporal_precision_count'])}** | **{fmt_stat(overall['precision_at_k'], overall['precision_at_k_count'])}** | **{fmt_stat(overall['grounding_rate'], overall['grounding_rate_count'])}** | **{fmt_stat(overall['refusal_recall'], overall['refusal_recall_count'])}** | **{fmt_stat(overall['false_refusal_rate'], overall['false_refusal_count'])}** |",
        f"",
    ])

    if "compression_ratio" in overall and overall.get("compression_ratio") is not None:
        lines.extend([
            f"## Episode & System Efficiency Metrics (Chunk 2)",
            f"",
            f"| Metric | Value |",
            f"|---|:---:|",
            f"| **Database Compression Ratio (Captures ÷ Episodes)** | {overall.get('compression_ratio')}x |",
            f"| **Mean Distinct Episodes @ {meta['k']}** | {overall.get('distinct_episodes_at_k')} / {meta['k']} |",
            f"| **Mean Context Characters per Query** | {overall.get('mean_context_chars')} chars |",
            f"| **Mean Query Latency** | {overall.get('mean_generation_latency_ms')} ms |",
            f"",
        ])

    # Delta table if baseline data is provided
    if baseline_data and "overall" in baseline_data:
        base_over = baseline_data["overall"]
        base_tag = compare_tag or baseline_data.get("metadata", {}).get("tag", "baseline")
        lines.extend([
            f"## Delta Comparison vs `{base_tag}`",
            f"",
            f"| Metric | `{base_tag}` | `{tag}` | Delta (Δ) |",
            f"|---|:---:|:---:|:---:|",
            f"| **Temporal Precision** | {fmt_stat(base_over.get('temporal_precision'))} | {fmt_stat(overall.get('temporal_precision'))} | **{fmt_delta(overall.get('temporal_precision'), base_over.get('temporal_precision'))}** |",
            f"| **Precision@{meta['k']}** | {fmt_stat(base_over.get('precision_at_k'))} | {fmt_stat(overall.get('precision_at_k'))} | **{fmt_delta(overall.get('precision_at_k'), base_over.get('precision_at_k'))}** |",
            f"| **Grounding Rate** | {fmt_stat(base_over.get('grounding_rate'))} | {fmt_stat(overall.get('grounding_rate'))} | **{fmt_delta(overall.get('grounding_rate'), base_over.get('grounding_rate'))}** |",
            f"| **Refusal Recall (Should Refuse)** | {fmt_stat(base_over.get('refusal_recall', 0.0))} | {fmt_stat(overall.get('refusal_recall'))} | **{fmt_delta(overall.get('refusal_recall'), base_over.get('refusal_recall', 0.0))}** |",
            f"| **False Refusal Rate (Non-Refuse)** | {fmt_stat(base_over.get('false_refusal_rate', 0.0))} | {fmt_stat(overall.get('false_refusal_rate'))} | **{fmt_delta(overall.get('false_refusal_rate'), base_over.get('false_refusal_rate', 0.0))}** |",
            f"",
        ])

    lines.extend([
        f"## Detailed Query Breakdown",
        f"",
        f"| ID | Category | Query | Temp Prec | P@{meta['k']} | Grounding | Refused? | Should Refuse? | Reason |",
        f"|---|---|---|:---:|:---:|:---:|:---:|:---:|---|",
    ])

    for q in results["queries"]:
        m = q["metrics"]
        e = q["execution"]
        gt = q["ground_truth"]
        tp = fmt_stat(m["temporal_precision"])
        pk = fmt_stat(m["precision_at_k"])
        gr = fmt_stat(m["grounding_rate"])
        is_ref = "Yes" if e["is_refusal"] else "No"
        sh_ref = "Yes" if gt["should_refuse"] else "No"
        reason = e.get("refusal_reason") or "—"
        q_safe = q["query"].replace("|", "\\|")
        lines.append(
            f"| {q['id']} | {q['category']} | {q_safe} | {tp} | {pk} | {gr} | {is_ref} | {sh_ref} | {reason} |"
        )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Run evaluation benchmark on OmniContext frozen DB snapshot."
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        default=None,
        help="Path to the frozen SQLite database snapshot (positional argument).",
    )
    parser.add_argument(
        "--db",
        dest="db_flag",
        default=None,
        help="Path to the frozen SQLite database snapshot (alternative flag).",
    )
    parser.add_argument(
        "--queries",
        default=str(PROJECT_ROOT / "evaluation" / "queries.json"),
        help="Path to queries.json file (default: evaluation/queries.json).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "evaluation" / "results"),
        help="Directory to save evaluation results (default: evaluation/results).",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Top-K cutoff for precision@k calculation (default: 5).",
    )
    parser.add_argument(
        "--tag",
        default="baseline",
        help="Run identifier tag for output filenames (default: baseline).",
    )
    parser.add_argument(
        "--compare-tag",
        default=None,
        help="Tag of previous evaluation run to compare delta against (default: baseline if tag != baseline).",
    )

    args = parser.parse_args()

    raw_db = args.db_path or args.db_flag
    if not raw_db:
        default_db = PROJECT_ROOT / "data" / "context.db"
        if default_db.exists():
            logger.info(f"No DB path provided in argv; using default: {default_db}")
            target_db = default_db
        else:
            parser.error("A database snapshot path must be provided via argv (e.g. `python evaluation/run_eval.py data/context.db`).")
    else:
        target_db = Path(raw_db)

    run_evaluation(
        db_path=target_db,
        queries_path=Path(args.queries),
        output_dir=Path(args.output_dir),
        k=args.k,
        tag=args.tag,
        compare_tag=args.compare_tag,
    )


if __name__ == "__main__":
    main()
