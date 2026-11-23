"""
Script to run EPISODE_SIM_THRESHOLD sweep (0.80 - 0.95 in 0.05 steps)
and report episode count, compression ratio, and precision@5.
"""

import os
import sys
from pathlib import Path

# Set offline flags and path
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["USE_TEMPORAL"] = "true"
os.environ["USE_EPISODES"] = "true"

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage.db import DatabaseManager
from processing.embed import EmbeddingGenerator
from intelligence.rag import RAGAgent
from intelligence.segmenter import build_episodes
from evaluation.run_eval import load_queries, compute_precision_at_k


def main():
    db = DatabaseManager()
    emb = EmbeddingGenerator()
    rag = RAGAgent(db, emb)
    queries, ref_now = load_queries(Path("evaluation/queries.json"))

    print("\n" + "=" * 70)
    print("  OmniContext: Threshold Sweep (0.80 - 0.95)")
    print("=" * 70)
    print(f"| {'Threshold':^11} | {'Episode Count':^15} | {'Compression Ratio':^19} | {'Precision@5':^13} |")
    print(f"|{'-'*13}|{'-'*17}|{'-'*21}|{'-'*15}|")

    total_caps = db.conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]

    sweep_results = []
    for th in [0.80, 0.85, 0.90, 0.95]:
        ep_count = build_episodes(db, sim_threshold=th, replace_existing=True)
        p_at_ks = []
        for q in queries:
            gt = q["ground_truth"]
            res = rag.query(q["query"], reference_now=ref_now)
            p = compute_precision_at_k(res["sources"], gt["relevant_capture_ids"], 5, gt["should_refuse"])
            if p is not None:
                p_at_ks.append(p)
        mean_p5 = sum(p_at_ks) / len(p_at_ks) if p_at_ks else 0.0
        comp = total_caps / ep_count if ep_count > 0 else 1.0
        print(f"| {th:^11.2f} | {ep_count:^15} | {f'{comp:.2f}x':^19} | {f'{mean_p5*100:.1f}%':^13} |")
        sweep_results.append((th, ep_count, comp, mean_p5))

    print("=" * 70)

    # Re-build with selected best threshold (0.85)
    build_episodes(db, sim_threshold=0.85, replace_existing=True)


if __name__ == "__main__":
    main()
