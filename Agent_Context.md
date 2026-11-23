# Project Context: OmniContext — Privacy-First Ambient Context Engine

This document is the full context for this project. Read it before writing or modifying any code. It explains what we're building, why, how work is prioritized, what's already been decided, and what complications to watch for. Refer back to this document when making architectural decisions — don't re-derive priorities from the code alone.

---

## 1. What This Project Is

OmniContext is a **100% local background daemon** that continuously captures a user's screen and system audio, extracts text from it (OCR/STT), stores it in an encrypted local database, and exposes a natural-language query interface so the user can ask things like:

> "What repo was I looking at around 3pm yesterday?"
> "What did I discuss on that call this morning about the API redesign?"

All capture, processing, storage, and inference happens **on-device**. No cloud calls, no telemetry, no external API dependency for the core pipeline. This is a privacy-first alternative to tools like Rewind.ai.

**This is a BTech (undergraduate CS) 7th-semester major project.** It needs to be completed within a semester, demonstrate genuine technical depth (not just gluing together libraries), and be strong enough to discuss in technical interviews and put on a resume. It is not a startup, not a product — it's an academic project with an eye toward technical credibility.

---

## 2. Why This Project (Motivation & Positioning)

### 2.1 The problem space
Tools that passively record a user's screen/audio to build a searchable memory already exist. The two most relevant open-source prior-art projects are:

- **`mediar-ai/screenpipe`** — local-first screen + audio capture, OCR/STT, plugin pipeline. Very mature, close to what we're building on the capture side.
- **`openrecall/openrecall`** — open-source Rewind.ai-style clone: screen capture, OCR, semantic search over history.

Both of these solve **capture** reasonably well. Neither of them solves the **hard problem that comes after capture**: how do you turn a firehose of near-duplicate, timestamped, multi-modal data into an answer the user can actually trust?

### 2.2 Our thesis
> **Existing local-context tools solve capture but not the harder problem of converting near-duplicate ambient data into trustworthy, temporally-grounded answers.**

This is the sentence that should appear, near-verbatim, in the README, the final report abstract, and any interview answer about this project. Every architectural decision should be evaluated against whether it serves this thesis.

### 2.3 What this means practically
We are **not** trying to out-engineer screenpipe's capture pipeline. We are not trying to build a better OCR engine. Those are solved problems — we integrate existing tools for them. Our differentiated, defensible contribution is the **retrieval + reasoning layer** sitting on top of captured data (the `intelligence/` module).

If a design decision doesn't serve the thesis (better temporal grounding, better dedup, better trustworthy generation), it should be built as simply and correctly as possible and not gold-plated.

---

## 3. How We Are Proceeding (Division of Labor)

The project is explicitly split into two tiers of effort. This split should be visible in how the codebase is organized, how commits are messaged, and how the final report is structured.

### Tier 1 — Integration Work (target: 3–4 weeks, "get it right, don't innovate")
These are necessary supporting infrastructure. Correctness, stability, and reasonable performance matter. Novelty does not. Use existing, well-tested libraries; don't reinvent them.

- **Capture pipeline** (`capture/`): OS-level screen frame capture at adaptive frame rate (1–5 FPS depending on activity/idle detection) and system audio buffer capture.
- **OCR/STT** (`processing/`): Tesseract (or platform-native OCR) for screen text, whisper.cpp (quantized) for audio transcription.
- **Storage** (`storage/`): SQLite with `sqlite-vec` for vector search and FTS5 for BM25 keyword search, combined into a hybrid retrieval index.
- **Security/lifecycle**: AES-256 encryption at rest, and a configurable retention/pruning policy (storage quota + temporal decay).

None of these need to beat state-of-the-art. They need to work reliably and stay out of the way of the interesting part.

### Tier 2 — Thesis Work (the actual contribution, most of our engineering time and all of our writeup depth)
This lives primarily in `intelligence/`. These are the four hard problems this project actually exists to solve:

1. **Temporal query decomposition** — User queries mix semantic content ("what repo was I looking at") with temporal constraints ("around 3pm yesterday"). Naive RAG treats the whole query as one embedding and fails at temporal filtering, because embeddings don't encode time well. We need a decomposition step (rule-based parser, small classifier, or prompted SLM) that separates the temporal constraint from the semantic constraint *before* retrieval — filter by time window first, then rank semantically within that window.

2. **Session/event segmentation (deduplication)** — At 1–5 FPS, a single 20-minute coding session produces hundreds of near-identical OCR captures. Feeding all of this into the index (and later, into an SLM's context window) is wasteful and hurts retrieval precision. We need a clustering/segmentation layer that collapses contiguous near-duplicate captures into a single coherent "episode" with a start/end timestamp, before it's embedded and indexed.

3. **Retrieval-conditioned generation with grounding** — Because this is personal historical context (not a general document corpus), hallucination is especially costly — a wrong answer about "what you were doing at 3pm" is worse than useless, it's actively misleading. The SLM must be constrained to answer only from retrieved snippets, must cite timestamps for its claims, and must have an explicit low-confidence refusal path ("I don't have enough context to answer that confidently") rather than confabulating.

4. **Quantization-level benchmarking** — Since this runs locally on commodity hardware, model choice and quantization level directly determine whether the system is usable. We will benchmark candidate SLMs (Qwen2.5-1.5B, Qwen2.5-3B, Llama-3.2-3B) at different quantization levels (Q4 vs Q8) via ONNX Runtime or Ollama, measuring latency and answer quality tradeoffs, and justify our final model choice with data rather than assumption.

---

## 4. Complications & Known Risks

Be aware of these while building — they are not hypothetical, they are likely to bite us.

- **Embedding model reuse pitfall**: The embedding model (currently `all-MiniLM-L6-v2`) must be loaded once at daemon startup and cached/reused as a singleton. It must NOT be reinstantiated per capture or per query — model load time is ~20+ seconds including any network calls, and this will silently tank throughput if called per-frame.
- **Near-duplicate embeddings will dominate naive top-k retrieval.** Because sequential screen captures are highly similar, naive cosine-similarity top-k search will often return 10 near-identical chunks from the same 30-second window instead of diverse, relevant results. This is precisely why segmentation (Tier 2, item 2) needs to happen before indexing, not as an afterthought.
- **Temporal expressions are linguistically messy.** "Yesterday afternoon," "a couple hours ago," "last Tuesday" all need robust parsing. Decide early whether this is handled by a lightweight rule-based/regex parser (fast, deterministic, easier to evaluate) or delegated to the SLM itself (more flexible, harder to evaluate/debug). This is a real design decision, not a triviality — document the tradeoff in the report.
- **CPU-only inference constraints.** Both embedding and generation are running on CPU (per the current setup). Latency budgets need to be established early — if a query takes 30+ seconds end-to-end, that's a usability finding worth reporting, not something to hide.
- **Evaluation is hard because ground truth is personal.** Standard RAG benchmarks don't apply — we will need to construct our own small evaluation set (~50 queries) against our own captured data, with manually verified correct answers, to measure retrieval precision and generation faithfulness. Build this evaluation harness early, not at the end — it's needed to justify every claim in Tier 2.
- **Privacy claims need to be actually true, not just asserted.** If "100% local, zero cloud calls" is a claim in the report, it needs to be verifiable (e.g., network calls disabled/monitored during operation, or an explicit allowlist showing the only external call is the one-time model download). Don't let a stray HTTP call to Hugging Face at runtime undermine the thesis — model weights should be downloaded once and cached locally, then the daemon should run fully offline.

---

## 5. What "Advancement" Looks Like (How Progress Should Be Framed)

When reporting progress (to me, to a supervisor, in commits), frame it against the four Tier 2 problems above, not against "which module is done." E.g.:

- ❌ "Finished the storage module."
- ✅ "Storage module (Tier 1) is functionally complete; starting on session segmentation (Tier 2, problem 2) — first pass will use a simple cosine-similarity threshold + temporal contiguity window, will evaluate against manual inspection of 20 sample sessions."

This keeps every status update tied to the thesis, which matters both for staying focused during development and for writing a coherent final report at the end.

---

## 6. Instructions for the Coding Agent

When implementing features:

1. **Default to simple, well-tested libraries for Tier 1 work.** Don't write custom OCR, custom audio capture, or a custom vector index from scratch — use `sqlite-vec`, Tesseract/platform OCR, whisper.cpp bindings.
2. **Slow down and discuss design tradeoffs for Tier 2 work** (temporal decomposition, segmentation, grounded generation, quantization benchmarking). These are the parts worth getting right, and worth documenting *why* a given approach was chosen over alternatives.
3. **Keep the module boundary between `intelligence/` (thesis) and everything else (infrastructure) clean.** `intelligence/` should be the largest, most-iterated-on, most-tested part of the codebase by the end of the project.
4. **Cache expensive resources (models) at startup**, never per-request.
5. **Write evaluation/benchmarking code early**, not as an afterthought — we need quantitative claims for the report, not just "it seems to work."
6. **When in doubt about scope, ask**: does this serve "converting near-duplicate ambient data into trustworthy, temporally-grounded answers"? If not, it's Tier 1 — build it simply and move on.

---

## 7. Current State (fill in / update as project progresses)

- Repo structure exists: `capture/`, `intelligence/`, `interface/`, `processing/`, `storage/`.
- Phase 1 (Data Validation & Taxonomy) is completed: pipeline robustness fixes applied, health check script added, and evaluation taxonomy designed with 24 template queries.
- Real ambient screen-capture dataset collected in `data/context.db` (~120 real captures across September 5 and November 23).
- Evaluation harness `evaluation/run_eval.py` and instantiated ground truth dataset `evaluation/queries.json` built.
- Baseline evaluation run completed (`evaluation/results/baseline_results.json` and `evaluation/results/baseline_summary.md`):
  - Overall Temporal Precision: 4.6% (13/24)
  - Precision@5: 0.8% (24/24)
  - Grounding Rate: 0.0% (24/24)
  - Refusal Recall: 0.0% (0/6)
  - False Refusal Rate: 0.0% (0/18)
- **Chunk 1 — Temporal Decomposition + Time-Filtered Retrieval (tag: `temporal`) COMPLETED**:
  - Implemented rule-based temporal parser `intelligence/temporal.py` (clock times, dates, relative offsets, day-parts, future expressions, intent detection, and residual extraction).
  - Sanitized FTS5 keyword leg in `storage/db.py` (`_fts_query`) to avoid syntax errors and support boolean term retrieval.
  - Implemented time-filtered hybrid search in `storage/db.py` using candidate SQL index pre-filtering, exact cosine similarity via NumPy on small windows, and rank fusion.
  - Added deterministic future time refusals and zero-data window refusals in `intelligence/rag.py`.
  - Added structured aggregation operators for `apps`, `duration`, `latest`, `earliest` intents.
  - All behavior toggleable via `config.USE_TEMPORAL`.
  - 34 unit tests in `tests/test_temporal.py` (all passing).
  - Evaluation results (`evaluation/results/temporal_results.json` and `temporal_summary.md`):
    - **Temporal Precision:** 79.2% (Δ +74.6% vs baseline)
    - **Precision@5:** 40.8% (Δ +40.0% vs baseline)
    - **Grounding Rate:** 27.1% (Δ +27.1% vs baseline)
    - **Refusal Recall (Should Refuse):** 50.0% (Δ +50.0% vs baseline)
    - **False Refusal Rate:** 0.0% (0/18)
    - Pure Temporal category Temporal Precision: 100.0%, P@5: 73.3%.
- **Chunk 2 — Episode Segmentation & Deduplication (tag: `episodes`) COMPLETED**:
  - Implemented single-pass episode segmenter in `intelligence/segmenter.py` (`build_episodes`, `ensure_episodes`) tracking running centroid, process continuity, and gap constraints without over-splitting on browser tab title changes.
  - Created tables `episodes`, `episode_captures`, and FTS virtual table `episodes_fts` with automated SQLite triggers in `storage/schema.sql`.
  - Added `search_episodes` in `storage/db.py` with candidate window pre-filtering, exact centroid cosine scoring in NumPy, BM25 text ranking, and RRF rank fusion.
  - Integrated episode retrieval and prompt context formatting into `intelligence/rag.py`, switchable via `config.USE_EPISODES`.
  - Created batch management script `scripts/build_episodes.py` and parameter sweep script `scripts/sweep_episodes.py`.
  - Performed threshold sweep across [0.80, 0.85, 0.90, 0.95] (selected `EPISODE_SIM_THRESHOLD = 0.85` for optimal compression-semantic trade-off).
  - 43 unit tests passing in `tests/test_segmenter.py` and `tests/test_temporal.py`.
  - Evaluation results (`evaluation/results/episodes_results.json` and `episodes_summary.md`):
    - **Temporal Precision:** 85.4% (Δ +6.2% vs `temporal`)
    - **Precision@5:** 40.0% (Δ -0.8% vs `temporal`)
    - **Hybrid Category Temporal Precision:** 68.3% (Δ +13.3% vs `temporal`)
    - **Grounding Rate:** 27.1%
    - **Refusal Recall (Should Refuse):** 50.0%
    - **False Refusal Rate (Non-Refuse):** 0.0% (0/18)
    - **Database Compression Ratio:** 1.09x
    - **Mean Distinct Episodes @ 5:** 4.38 / 5
    - **Mean Context Characters:** 3,610 chars
    - **Mean Query Latency:** 24.9 ms
- Next steps:
  1. Chunk 3 — Retrieval-conditioned generation with grounding and low-confidence refusal (tag: `grounding`).
