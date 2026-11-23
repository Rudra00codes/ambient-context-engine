# OmniContext Evaluation Results — Tag: `heldout_episodes`

- **Run Tag:** `heldout_episodes`
- **Timestamp:** `20261124_040100`
- **Database Snapshot:** `X:\InternProject\ambient-context-engine\data\context.db`
- **Reference Now:** `2026-11-24T03:55:00`
- **Queries Evaluated:** 10
- **Evaluation Metric Top-K:** 5

## Summary Table per Category

| Category | Queries | Temporal Precision | Precision@5 | Grounding Rate | Refusal Recall (Should Refuse) | False Refusal Rate (Non-Refuse) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Ambiguous** | 2 | N/A | 50.0% (2/2) | 50.0% (2/2) | 50.0% (1/2) | N/A |
| **Hybrid** | 2 | 100.0% (2/2) | 60.0% (2/2) | 0.0% (2/2) | N/A | 0.0% (0/2) |
| **Semantic** | 3 | N/A | 53.3% (3/3) | 0.0% (3/3) | N/A | 0.0% (0/3) |
| **Temporal** | 3 | 100.0% (3/3) | 66.7% (3/3) | 66.7% (3/3) | N/A | 0.0% (0/3) |
| **Overall** | **10** | **100.0% (5/10)** | **58.0% (10/10)** | **30.0% (10/10)** | **50.0% (1/2)** | **0.0% (0/8)** |

## Episode & System Efficiency Metrics (Chunk 2)

| Metric | Value |
|---|:---:|
| **Database Compression Ratio (Captures ÷ Episodes)** | 1.43x |
| **Mean Distinct Episodes @ 5** | 4.5 / 5 |
| **Mean Context Characters per Query** | 3070.2 chars |
| **Mean Query Latency** | 23.6 ms |

## Delta Comparison vs `baseline`

| Metric | `baseline` | `heldout_episodes` | Delta (Δ) |
|---|:---:|:---:|:---:|
| **Temporal Precision** | 4.6% | 100.0% | **+95.4%** |
| **Precision@5** | 0.8% | 58.0% | **+57.2%** |
| **Grounding Rate** | 0.0% | 30.0% | **+30.0%** |
| **Refusal Recall (Should Refuse)** | 0.0% | 50.0% | **+50.0%** |
| **False Refusal Rate (Non-Refuse)** | 0.0% | 0.0% | **0.0%** |

## Detailed Query Breakdown

| ID | Category | Query | Temp Prec | P@5 | Grounding | Refused? | Should Refuse? | Reason |
|---|---|---|:---:|:---:|:---:|:---:|:---:|---|
| HT1 | temporal | What was I working on in Arduino IDE between 2:20 AM and 2:40 AM on November 24? | 100.0% | 60.0% | 0.0% | No | No | — |
| HT2 | temporal | What apps did I use between 3:10 AM and 3:20 AM on November 24? | 100.0% | 40.0% | 100.0% | No | No | — |
| HT3 | temporal | When did I start working on November 24? | 100.0% | 100.0% | 100.0% | No | No | — |
| HS1 | semantic | Find captures where esp32_cam_streamer was open | N/A | 80.0% | 0.0% | No | No | — |
| HS2 | semantic | Where was I using Monkeytype typing test? | N/A | 40.0% | 0.0% | No | No | — |
| HS3 | semantic | Find where Pinterest was open | N/A | 40.0% | 0.0% | No | No | — |
| HH1 | hybrid | What project demo launcher was open in Windows Terminal around 2:30 AM on November 24? | 100.0% | 80.0% | 0.0% | No | No | — |
| HH2 | hybrid | What file was I editing in Antigravity IDE between 3:40 AM and 3:45 AM on November 24? | 100.0% | 40.0% | 0.0% | No | No | — |
| HA1 | ambiguous | What did the other person say during the WhatsApp call at 2:00 AM on November 24? | N/A | 0.0% | 0.0% | No | Yes | — |
| HA2 | ambiguous | What will I be coding tomorrow morning at 10 AM? | N/A | 100.0% | 100.0% | Yes | Yes | future_time |