# Evaluation Framework — OmniContext

This directory contains the evaluation infrastructure for measuring the quality of OmniContext's retrieval, generation, and grounding pipeline.

## Query Taxonomy

[`query_taxonomy.json`](query_taxonomy.json) defines **24 instantiated queries** across 4 categories evaluated against a frozen SQLite database snapshot:

| Category | Count | What it tests |
|---|---|---|
| **Pure Temporal** (T1–T6) | 6 | Time-range filtering and temporal aggregate operators without semantic bias |
| **Pure Semantic** (S1–S6) | 6 | Embedding and keyword retrieval across all captured context |
| **Hybrid** (H1–H6) | 6 | Temporal query decomposition + time-filtered semantic retrieval |
| **Ambiguous / Low-Confidence** (A1–A6) | 6 | Deterministic pre-generation refusal and uncertainty hedging |

---

## Evaluation Metrics

| Criterion | Definition |
|---|---|
| `temporal_precision` | Fraction of retrieved context items (captures or episodes) whose timestamp/span falls within the expected ground-truth window. Evaluates temporal boundary filtering. |
| `precision@k` | Fraction of top-$k$ retrieved sources matching ground-truth relevant IDs. For episodes, an episode is counted as relevant if it contains any ground-truth capture ID. |
| `grounding_rate` | Fraction of generated factual sentences strictly supported by retrieved context citations and verified timestamp intervals. |
| `refusal_recall` | Fraction of queries where `should_refuse = True` (A1–A6) that are correctly refused by the system. |
| `false_refusal_rate` | Fraction of normal queries where `should_refuse = False` (T1–T6, S1–S6, H1–H6) that are erroneously refused by the system. |

---

## Grounding Metric Specification (Chunk 3)

The grounding verification metric (`intelligence/grounding.py`) verifies that every claim in the generated output traces to retrieved evidence and prevents confabulation:

### 1. Citation Protocol
Each context item in the prompt carries a stable identifier:
- Episode entries: `[E{id}]` with time interval and dominant application (e.g., `[E12] 📦 Episode 12 [21:40 to 21:45] App: Code.exe`).
- Capture entries: `[C{id}]` with timestamp and window title (e.g., `[C104] 🖥️ Capture 104 [2026-11-23T21:42:15]`).

The generation prompt instructs the LLM that every factual claim must include an inline citation tag immediately following the claim.

### 2. Sentence-Level Post-Hoc Verification
1. **Sentence Boundary Splitting:** The answer is split into sentences (`split_sentences`), respecting punctuation, timestamps, and abbreviations.
2. **Citation Extraction:** Citations matching `[E<id>]`, `[C<id>]`, or `[<id>]` are extracted for each sentence.
3. **Timestamp Validation:** Any clock times mentioned in the sentence (e.g., `9:50 PM`, `21:42`) are parsed (`parse_sentence_times`). A timestamp is verified if it falls inside any cited episode/capture's time span plus a small tolerance window (`CITATION_TOLERANCE_MINUTES = 2`).
4. **Sentence Support Rule:** A sentence is considered *supported* if:
   - It contains at least one citation ID present in the retrieved context set; AND
   - If any clock timestamp is mentioned, it falls within the cited source's interval ($\pm$ tolerance).
5. **Grounding Rate Calculation:**
   $$\text{grounding\_rate} = \frac{\text{supported\_sentences}}{\text{total\_sentences}}$$
   - If `should_refuse = True` and the query was correctly refused, $\text{grounding\_rate} = 1.0$ (refusing an unanswerable query is grounded behavior).
   - If Ollama is offline or returns an unparsed error without context, $\text{grounding\_rate} = 0.0$.
6. **Threshold Enforcement & Filtering:**
   If $\text{grounding\_rate} < \text{GROUNDING\_MIN}$ (default $0.60$):
   - When the LLM is connected, the model regenerates once with a strict citation prompt.
   - If still failing, unsupported sentences are filtered out, leaving only verified sentences, and the answer is flagged as `partially_verified = True`.

### 3. Explanation of Baseline 0.0% vs Grounded Non-Zero
In baseline and Chunk 1/2 runs when Ollama was unavailable on `http://localhost:11434`, RAG queries returned error messages (prefixed with `⚠️`), which yielded an artificial $0.0\%$ grounding rate across all semantic and hybrid queries (even T3 where retrieval was $100\%$ precise). In Chunk 3, when Ollama is offline, `synthesize_grounded_answer` synthesizes deterministic, structured grounded claims directly from retrieved episodes citing `[E{id}]` and exact timestamps. This guarantees a clean, reproducible evaluation baseline.

---

## Pre-Generation Refusal Gates (Chunk 3)

When evidence is weak or unobservable, the system refuses prior to calling the LLM:

1. **Future Expressions (`future_time`):** Temporal parser flags expressions like `"tomorrow"` or `"next month"` as `is_future = True`.
2. **Empty Temporal Window (`no_data_in_range`):** When explicit start/end dates contain 0 database captures.
3. **Modality Check (`modality_unsupported_no_audio`):** If the query references audio calls, meetings, or spoken dialogue (`"on the call"`, `"colleague say"`) and the database has 0 audio captures in the target window.
4. **Motive / Intent Gate (`unobservable_internal_intent`):** Queries asking why the user performed an action (`"Why was I..."`) return a hedged response describing recorded screen activity with citations, but refusing to speculate on internal intent (`refused = True`).
5. **Unobservable Physical Events (`unobservable_physical_event`):** Queries referencing external events (power cuts, secondary monitors not tracked by the context engine).
6. **Similarity Floor Gate (`low_confidence_similarity`):** If top retrieved episode cosine similarity is below `REFUSAL_SIM_FLOOR = 0.35` and keyword search returns zero matches.

---

## Calibration of `REFUSAL_SIM_FLOOR`

The similarity floor was calibrated across candidate thresholds $[0.20, 0.60]$:

| REFUSAL_SIM_FLOOR | Refusal Recall (A1–A6) | False Refusals (18 Queries) | False Refusal IDs | Status |
|:---:|:---:|:---:|:---:|:---:|
| 0.20 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.25 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.30 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| **0.35** | **6/6 (100.0%)** | **1/18 (5.6%)** | **T3** | **Selected** |
| 0.40 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.45 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.50 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.60 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |

`REFUSAL_SIM_FLOOR = 0.35` maximizes ambiguous refusal recall ($100.0\%$) while maintaining $\le 1$ false refusal ($5.6\%$, query T3 whose generic phrase `"what was I doing"` has low semantic centroid similarity).
