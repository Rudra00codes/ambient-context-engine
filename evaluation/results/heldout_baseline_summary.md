# OmniContext Evaluation Results — Tag: `heldout_baseline`

- **Run Tag:** `heldout_baseline`
- **Timestamp:** `20261124_040023`
- **Database Snapshot:** `X:\InternProject\ambient-context-engine\data\context.db`
- **Reference Now:** `2026-11-24T03:55:00`
- **Queries Evaluated:** 10
- **Evaluation Metric Top-K:** 5

## Summary Table per Category

| Category | Queries | Temporal Precision | Precision@5 | Grounding Rate | Refusal Recall (Should Refuse) | False Refusal Rate (Non-Refuse) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Ambiguous** | 2 | N/A | 0.0% (2/2) | 0.0% (2/2) | 0.0% (0/2) | N/A |
| **Hybrid** | 2 | 10.0% (2/2) | 0.0% (2/2) | 0.0% (2/2) | N/A | 0.0% (0/2) |
| **Semantic** | 3 | N/A | 26.7% (3/3) | 0.0% (3/3) | N/A | 0.0% (0/3) |
| **Temporal** | 3 | 10.0% (3/3) | 0.0% (3/3) | 0.0% (3/3) | N/A | 0.0% (0/3) |
| **Overall** | **10** | **10.0% (5/10)** | **8.0% (10/10)** | **0.0% (10/10)** | **0.0% (0/2)** | **0.0% (0/8)** |

## Episode & System Efficiency Metrics (Chunk 2)

| Metric | Value |
|---|:---:|
| **Database Compression Ratio (Captures ÷ Episodes)** | 1.43x |
| **Mean Distinct Episodes @ 5** | 5.0 / 5 |
| **Mean Context Characters per Query** | 5401.1 chars |
| **Mean Query Latency** | 30.7 ms |

## Delta Comparison vs `baseline`

| Metric | `baseline` | `heldout_baseline` | Delta (Δ) |
|---|:---:|:---:|:---:|
| **Temporal Precision** | 4.6% | 10.0% | **+5.4%** |
| **Precision@5** | 0.8% | 8.0% | **+7.2%** |
| **Grounding Rate** | 0.0% | 0.0% | **0.0%** |
| **Refusal Recall (Should Refuse)** | 0.0% | 0.0% | **0.0%** |
| **False Refusal Rate (Non-Refuse)** | 0.0% | 0.0% | **0.0%** |

## Detailed Query Breakdown

| ID | Category | Query | Temp Prec | P@5 | Grounding | Refused? | Should Refuse? | Reason |
|---|---|---|:---:|:---:|:---:|:---:|:---:|---|
| HT1 | temporal | What was I working on in Arduino IDE between 2:20 AM and 2:40 AM on November 24? | 10.0% | 0.0% | 0.0% | No | No | — |
| HT2 | temporal | What apps did I use between 3:10 AM and 3:20 AM on November 24? | 0.0% | 0.0% | 0.0% | No | No | — |
| HT3 | temporal | When did I start working on November 24? | 20.0% | 0.0% | 0.0% | No | No | — |
| HS1 | semantic | Find captures where esp32_cam_streamer was open | N/A | 0.0% | 0.0% | No | No | — |
| HS2 | semantic | Where was I using Monkeytype typing test? | N/A | 40.0% | 0.0% | No | No | — |
| HS3 | semantic | Find where Pinterest was open | N/A | 40.0% | 0.0% | No | No | — |
| HH1 | hybrid | What project demo launcher was open in Windows Terminal around 2:30 AM on November 24? | 20.0% | 0.0% | 0.0% | No | No | — |
| HH2 | hybrid | What file was I editing in Antigravity IDE between 3:40 AM and 3:45 AM on November 24? | 0.0% | 0.0% | 0.0% | No | No | — |
| HA1 | ambiguous | What did the other person say during the WhatsApp call at 2:00 AM on November 24? | N/A | 0.0% | 0.0% | No | Yes | — |
| HA2 | ambiguous | What will I be coding tomorrow morning at 10 AM? | N/A | 0.0% | 0.0% | No | Yes | — |