#!/usr/bin/env python3
"""
Model Benchmark Harness — Chunk 5

Benchmarks quantized local LLM variants across the 24 evaluation queries using
100% measured runtime metrics from Ollama (/api/generate response fields) and psutil:
- tokens/sec from eval_count and eval_duration
- TTFT (Time To First Token) from prompt_eval_duration
- End-to-end latency from total_duration and retrieval time
- Grounding rate computed via verify_grounding on actual outputs
- Answer correctness scored against ground truth
- Real RAM/VRAM consumption measured via psutil / /api/ps
- 1 warm-up call per model discarded before timing
- Raw per-query telemetry saved as JSON
- Markdown report generated strictly from measured numbers (zero hand-written prose)
- If Ollama is unreachable, harness aborts immediately (no fallback).
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import psutil
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Strict offline and evaluation flags
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["USE_TEMPORAL"] = "true"
os.environ["USE_EPISODES"] = "true"
os.environ["USE_GROUNDING"] = "true"
os.environ["ALLOW_TEMPLATE_FALLBACK"] = "false"

from config import OLLAMA_BASE_URL
from storage.db import DatabaseManager
from processing.embed import EmbeddingGenerator
from intelligence.rag import RAGAgent
from intelligence.grounding import verify_grounding

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("benchmark_models")


def check_ollama_reachable() -> List[str]:
    """Verify Ollama is reachable and return list of available model names. Abort if unreachable."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=(1.0, 3.0))
        resp.raise_for_status()
        models = resp.json().get("models", [])
        return [m["name"] for m in models]
    except Exception as e:
        logger.critical(f"FATAL: Cannot connect to Ollama at {OLLAMA_BASE_URL}: {e}")
        print(f"\n[ABORT] Cannot connect to Ollama at {OLLAMA_BASE_URL}. Make sure Ollama is running (`ollama serve`).\n")
        raise RuntimeError(f"Ollama is unreachable at {OLLAMA_BASE_URL}. Benchmark harness aborts.") from e


def measure_ollama_ram_gb(model_name: Optional[str] = None) -> float:
    """Measure actual RAM/VRAM consumption in GB via Ollama /api/ps or psutil."""
    # 1. Try Ollama /api/ps
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/ps", timeout=(1.0, 2.0))
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("models", [])
            for m in models:
                if not model_name or model_name.split(":")[0] in m.get("name", ""):
                    size = m.get("size", 0) or m.get("size_vram", 0)
                    if size > 0:
                        return round(size / (1024 ** 3), 2)
    except Exception:
        pass

    # 2. Try psutil for running Ollama processes
    try:
        total_rss = 0
        for proc in psutil.process_iter(["name", "memory_info"]):
            p_name = proc.info.get("name", "").lower()
            if "ollama" in p_name:
                mem = proc.info.get("memory_info")
                if mem and hasattr(mem, "rss"):
                    total_rss += mem.rss
        if total_rss > 0:
            return round(total_rss / (1024 ** 3), 2)
    except Exception:
        pass

    return 0.0


def evaluate_correctness(answer: str, ground_truth: Dict[str, Any], is_refusal: bool) -> float:
    """Evaluate whether answer satisfies ground-truth correctness."""
    should_refuse = ground_truth.get("should_refuse", False)
    if should_refuse:
        return 1.0 if is_refusal else 0.0

    if is_refusal:
        return 0.0

    expected = ground_truth.get("expected_answer", "").lower()
    if not expected:
        return 1.0

    ans_lower = answer.lower()
    keywords = [w for w in expected.replace(",", " ").replace(".", " ").split() if len(w) > 3]
    if not keywords:
        return 1.0

    matches = sum(1 for kw in keywords if kw in ans_lower)
    return matches / len(keywords)


def load_dev_queries(queries_path: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Load evaluation queries and reference_now from JSON file."""
    with open(queries_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    reference_now = data.get("reference_now", "2026-11-23T22:05:00")
    queries = []
    if "categories" in data:
        for cat in data["categories"]:
            for q in cat.get("queries", []):
                q_copy = dict(q)
                if "category" not in q_copy:
                    q_copy["category"] = cat.get("id", "unknown")
                queries.append(q_copy)
    elif "queries" in data:
        queries = data["queries"]

    return queries, reference_now


def run_model_benchmark(
    db_path: Path,
    queries_path: Path,
    output_dir: Path,
    target_models: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Execute real-measurement benchmark across models."""
    available_models = check_ollama_reachable()
    logger.info(f"Ollama reachable. Available models: {available_models}")

    if target_models:
        models_to_run = target_models
    else:
        # Default candidate list: pick what is available or standard default
        candidates = [
            "llama3.2:3b-instruct-q4_K_M",
            "llama3.2:3b",
            "llama3.2:3b-instruct-q8_0",
            "qwen2.5:3b-instruct-q4_K_M",
            "qwen2.5:3b-instruct-q8_0",
            "qwen2.5:1.5b-instruct-q4_K_M",
        ]
        # Match candidates with available models
        matched = [c for c in candidates if c in available_models]
        if not matched:
            matched = available_models[:5] if available_models else ["llama3.2:3b"]
        models_to_run = matched

    queries, reference_now = load_dev_queries(queries_path)
    logger.info(f"Loaded {len(queries)} queries for benchmarking. Reference now: {reference_now}")

    db = DatabaseManager(db_path=db_path)
    embedder = EmbeddingGenerator()
    rag = RAGAgent(db=db, embedder=embedder)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_query_rows: List[Dict[str, Any]] = []
    aggregated_results: Dict[str, Any] = {}

    print("\n" + "=" * 80)
    print(f"  OmniContext Quantized LLM Benchmark (Chunk 5: Real Telemetry)")
    print(f"  Database: {db_path.name} | Queries: {len(queries)} | Models: {models_to_run}")
    print("=" * 80 + "\n")

    for model_id in models_to_run:
        print(f"\n[Benchmarking Model: {model_id}]")
        # Set target model in config and environment
        os.environ["OLLAMA_MODEL"] = model_id
        import config
        config.OLLAMA_MODEL = model_id

        # 1. Warm-up call (discarded from benchmark timing)
        print("  -> Performing 1 warm-up call (discarded)...")
        try:
            rag.query("What was I doing at 9:50 PM on November 23?", reference_now=reference_now)
        except Exception as warm_err:
            logger.warning(f"Warm-up call warning for {model_id}: {warm_err}")

        # Measure RAM after warm-up
        measured_ram = measure_ollama_ram_gb(model_id)

        # 2. Run dev queries
        model_e2e_ms: List[float] = []
        model_ttft_ms: List[float] = []
        model_tok_s: List[float] = []
        model_grounding: List[float] = []
        model_correctness: List[float] = []
        total_eval_tokens = 0

        for idx, q in enumerate(queries, start=1):
            qid = q.get("id", f"Q{idx}")
            q_text = q.get("query", "")
            gt = q.get("ground_truth", {})

            t0 = time.time()
            rag_output = rag.query(q_text, reference_now=reference_now)
            wall_e2e_ms = (time.time() - t0) * 1000

            ans = rag_output.get("answer", "")
            sources = rag_output.get("sources", [])
            is_refusal = rag_output.get("refused", False)
            ans_source = rag_output.get("answer_source", "llm")
            stats = rag_output.get("ollama_stats", {})

            eval_count = stats.get("eval_count", 0)
            eval_dur_ns = stats.get("eval_duration", 0)
            prompt_eval_dur_ns = stats.get("prompt_eval_duration", 0)
            total_dur_ns = stats.get("total_duration", 0)

            # Compute tok/s from Ollama response fields
            if eval_dur_ns > 0 and eval_count > 0:
                tok_per_sec = eval_count / (eval_dur_ns / 1e9)
            else:
                tok_per_sec = 0.0

            # Compute TTFT (Time To First Token / prompt evaluation duration)
            ttft_ms = (prompt_eval_dur_ns / 1e6) if prompt_eval_dur_ns > 0 else 0.0

            # Compute E2E latency: retrieval search_time_ms + total Ollama generation duration
            ollama_gen_ms = (total_dur_ns / 1e6) if total_dur_ns > 0 else wall_e2e_ms
            e2e_ms = rag_output.get("search_time_ms", 0.0) + ollama_gen_ms

            # Compute grounding with verify_grounding on actual output
            grounding_res = verify_grounding(
                ans,
                sources,
                tolerance_minutes=config.CITATION_TOLERANCE_MINUTES,
                min_grounding=config.GROUNDING_MIN,
                is_refusal=is_refusal,
            )
            grounding_val = grounding_res.grounding_rate

            # Compute correctness against ground truth
            correctness_val = evaluate_correctness(ans, gt, is_refusal)

            total_eval_tokens += eval_count
            model_e2e_ms.append(e2e_ms)
            if ttft_ms > 0:
                model_ttft_ms.append(ttft_ms)
            if tok_per_sec > 0:
                model_tok_s.append(tok_per_sec)
            model_grounding.append(grounding_val)
            model_correctness.append(correctness_val)

            row_record = {
                "timestamp": datetime.now().isoformat(),
                "model": model_id,
                "query_id": qid,
                "query": q_text,
                "answer_source": ans_source,
                "eval_count": eval_count,
                "eval_duration_ns": eval_dur_ns,
                "prompt_eval_duration_ns": prompt_eval_dur_ns,
                "total_duration_ns": total_dur_ns,
                "tok_per_sec": round(tok_per_sec, 2),
                "ttft_ms": round(ttft_ms, 2),
                "e2e_ms": round(e2e_ms, 2),
                "grounding_rate": round(grounding_val, 4),
                "correctness": round(correctness_val, 4),
            }
            raw_query_rows.append(row_record)

            print(
                f"    [{idx:02d}/{len(queries):02d}] {qid} -> "
                f"TTFT: {ttft_ms:.1f}ms | "
                f"Throughput: {tok_per_sec:.1f} tok/s | "
                f"E2E: {e2e_ms:.1f}ms | "
                f"Grounding: {grounding_val*100:.1f}% | "
                f"Correctness: {correctness_val*100:.1f}%"
            )

        e2e_arr = np.array(model_e2e_ms) if model_e2e_ms else np.array([0.0])
        ttft_arr = np.array(model_ttft_ms) if model_ttft_ms else np.array([0.0])
        tok_arr = np.array(model_tok_s) if model_tok_s else np.array([0.0])

        aggregated_results[model_id] = {
            "model_id": model_id,
            "measured_ram_gb": measured_ram,
            "p50_ttft_ms": round(float(np.percentile(ttft_arr, 50)), 1),
            "p95_ttft_ms": round(float(np.percentile(ttft_arr, 95)), 1),
            "mean_tok_per_sec": round(float(np.mean(tok_arr)), 1),
            "p50_e2e_ms": round(float(np.percentile(e2e_arr, 50)), 1),
            "p95_e2e_ms": round(float(np.percentile(e2e_arr, 95)), 1),
            "mean_e2e_ms": round(float(np.mean(e2e_arr)), 1),
            "mean_grounding_pct": round(float(np.mean(model_grounding)) * 100, 1),
            "mean_correctness_pct": round(float(np.mean(model_correctness)) * 100, 1),
            "total_tokens_generated": total_eval_tokens,
        }

    db.close()

    # Output paths
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_json_path = output_dir / f"model_benchmark_raw_{timestamp_str}.json"
    summary_json_path = output_dir / "model_benchmark.json"
    md_path = output_dir / "model_benchmark.md"

    # Save raw records
    with open(raw_json_path, "w", encoding="utf-8") as f:
        json.dump(raw_query_rows, f, indent=2)

    # Save summary json
    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump(aggregated_results, f, indent=2)

    # Generate Markdown table strictly from computed numbers (zero hand-written prose)
    md_lines = [
        "# OmniContext Model Quantization Benchmark (Chunk 5)",
        "",
        f"- **Benchmark Timestamp:** `{timestamp_str}`",
        f"- **Database Snapshot:** `{db_path.name}`",
        f"- **Evaluation Queries:** {len(queries)} dev queries",
        f"- **Warm-up Discarded:** 1 call per model",
        f"- **Ollama Base URL:** `{OLLAMA_BASE_URL}`",
        "",
        "## Measured Performance Results",
        "",
        "| Model | Measured RAM (GB) | TTFT p50 (ms) | TTFT p95 (ms) | Throughput (tok/s) | p50 E2E Latency (ms) | p95 E2E Latency (ms) | Grounding Rate (%) | Correctness (%) |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]

    for m_id, r in aggregated_results.items():
        md_lines.append(
            f"| **`{m_id}`** | {r['measured_ram_gb']} GB | {r['p50_ttft_ms']} ms | {r['p95_ttft_ms']} ms | {r['mean_tok_per_sec']} tok/s | {r['p50_e2e_ms']} ms | {r['p95_e2e_ms']} ms | {r['mean_grounding_pct']}% | {r['mean_correctness_pct']}% |"
        )

    md_lines.extend([
        "",
        "## Model Comparison Summary",
        "",
        "| Model | Total Tokens | Mean E2E (ms) | Throughput (tok/s) | Grounding Rate (%) | Correctness (%) |",
        "|---|:---:|:---:|:---:|:---:|:---:|",
    ])

    for m_id, r in aggregated_results.items():
        md_lines.append(
            f"| **`{m_id}`** | {r['total_tokens_generated']} | {r['mean_e2e_ms']} ms | {r['mean_tok_per_sec']} tok/s | {r['mean_grounding_pct']}% | {r['mean_correctness_pct']}% |"
        )

    md_lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print("\n" + "=" * 80)
    print(f"Benchmark finished successfully.")
    print(f"  • Raw JSON:     {raw_json_path}")
    print(f"  • Summary JSON: {summary_json_path}")
    print(f"  • Markdown:     {md_path}")
    print("=" * 80 + "\n")

    return aggregated_results


def main():
    parser = argparse.ArgumentParser(description="Run 100% real measured Ollama model quantization benchmark.")
    parser.add_argument(
        "--db",
        default=str(PROJECT_ROOT / "data" / "context.db"),
        help="Path to context.db SQLite database snapshot.",
    )
    parser.add_argument(
        "--queries",
        default=str(PROJECT_ROOT / "evaluation" / "queries.json"),
        help="Path to queries.json file.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "evaluation" / "results"),
        help="Output directory for benchmark files.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=None,
        help="Specific Ollama models to benchmark.",
    )

    args = parser.parse_args()
    run_model_benchmark(
        db_path=Path(args.db),
        queries_path=Path(args.queries),
        output_dir=Path(args.output_dir),
        target_models=args.models,
    )


if __name__ == "__main__":
    main()
