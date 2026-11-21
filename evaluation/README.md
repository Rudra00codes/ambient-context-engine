# Evaluation Framework — OmniContext

This directory contains the evaluation infrastructure for measuring the quality of OmniContext's retrieval and generation pipeline. Evaluation is a **first-class concern**, not an afterthought — we need quantitative claims for the final report.

## Query Taxonomy

[`query_taxonomy.json`](query_taxonomy.json) defines **24 template queries** across 4 categories:

| Category | Count | What it tests |
|---|---|---|
| **Pure Temporal** (T1–T6) | 6 | Time-range filtering without semantic search |
| **Pure Semantic** (S1–S6) | 6 | Embedding/keyword retrieval without temporal filtering |
| **Hybrid** (H1–H6) | 6 | Temporal decomposition + semantic retrieval together (core thesis) |
| **Ambiguous / Low-Confidence** (A1–A6) | 6 | Refusal path — system must hedge or refuse, not confabulate |

### Evaluation Criteria

| Criterion | Definition |
|---|---|
| `temporal_precision` | % of retrieved results within the correct time window |
| `retrieval_precision` | Precision@k against manual relevance judgments |
| `completeness` | Recall — does the answer cover all relevant captures? |
| `grounding` | % of generated claims with a verifiable cited source |
| `refusal_accuracy` | % of low-confidence queries correctly refused/hedged |

## Workflow

### Phase 1: Data Accumulation (current)
1. Run `python main.py --no-audio` to accumulate screen capture data
2. Monitor with `python scripts/check_data.py`
3. Let it run for 2–3 days to build a realistic dataset

### Phase 2: Ground Truth Annotation
1. Pick 20–25 queries from the taxonomy templates, instantiated with real parameters from your captured data
2. For each query, manually verify the correct answer by inspecting the DB
3. Record the expected answer and relevant capture IDs in the `ground_truth` field

### Phase 3: Automated Evaluation (future)
1. Run each query through the retrieval + generation pipeline
2. Compare outputs against ground truth
3. Compute metrics per category and overall
4. Document findings in this directory

## Results

_Results will be added here once evaluation is run against real data._
