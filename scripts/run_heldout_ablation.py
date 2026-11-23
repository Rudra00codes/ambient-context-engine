#!/usr/bin/env python3
"""
Held-out Ablation Sweep — Chunk 4
Runs heldout.json across baseline, +temporal, +episodes, and +grounding
to produce the complete ablation progression table on held-out data.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
python_exe = sys.executable

configs = [
    {
        "tag": "heldout_baseline",
        "name": "Baseline (Unfiltered Hybrid)",
        "env": {"USE_TEMPORAL": "false", "USE_EPISODES": "false", "USE_GROUNDING": "false"},
    },
    {
        "tag": "heldout_temporal",
        "name": "+Temporal Decomposition",
        "env": {"USE_TEMPORAL": "true", "USE_EPISODES": "false", "USE_GROUNDING": "false"},
    },
    {
        "tag": "heldout_episodes",
        "name": "+Episodes (Chunk 2)",
        "env": {"USE_TEMPORAL": "true", "USE_EPISODES": "true", "USE_GROUNDING": "false"},
    },
    {
        "tag": "heldout_grounded",
        "name": "+Grounded Generation (Chunk 3 / Final)",
        "env": {"USE_TEMPORAL": "true", "USE_EPISODES": "true", "USE_GROUNDING": "true"},
    },
]

ablation_summary = {}

for cfg in configs:
    tag = cfg["tag"]
    print(f"\n---> Running ablation configuration: {cfg['name']} ({tag})...")
    env = os.environ.copy()
    env.update(cfg["env"])
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"

    cmd = [
        python_exe,
        str(PROJECT_ROOT / "evaluation" / "run_eval.py"),
        str(PROJECT_ROOT / "data" / "context.db"),
        "--queries", str(PROJECT_ROOT / "evaluation" / "heldout.json"),
        "--tag", tag,
    ]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error running {tag}:\n{res.stderr}")
        continue

    # Load result
    res_file = PROJECT_ROOT / "evaluation" / "results" / f"{tag}_results.json"
    if res_file.exists():
        with open(res_file, "r", encoding="utf-8") as f:
            d = json.load(f)
        ov = d["overall"]
        ablation_summary[tag] = {
            "name": cfg["name"],
            "temporal_precision": ov.get("temporal_precision"),
            "precision_at_k": ov.get("precision_at_k"),
            "grounding_rate": ov.get("grounding_rate"),
            "refusal_recall": ov.get("refusal_recall"),
            "false_refusal_rate": ov.get("false_refusal_rate"),
            "query_latency_ms": ov.get("mean_generation_latency_ms", 0.0),
        }
        print(f"    TempPrec: {ov['temporal_precision']*100 if ov['temporal_precision'] else 0:.1f}% | P@5: {ov['precision_at_k']*100:.1f}% | Grounding: {ov['grounding_rate']*100:.1f}% | RefusalRecall: {ov['refusal_recall']*100 if ov['refusal_recall'] else 0:.1f}% | FalseRefuse: {ov['false_refusal_rate']*100 if ov['false_refusal_rate'] else 0:.1f}%")

out_file = PROJECT_ROOT / "evaluation" / "results" / "heldout_ablation_summary.json"
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(ablation_summary, f, indent=2)
print(f"\nHeldout ablation summary written to {out_file}")
