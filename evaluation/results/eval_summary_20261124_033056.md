# OmniContext Evaluation Results — Tag: `grounded`

- **Run Tag:** `grounded`
- **Timestamp:** `20261124_033056`
- **Database Snapshot:** `X:\InternProject\ambient-context-engine\data\context.db`
- **Reference Now:** `2026-11-23T22:05:00`
- **Queries Evaluated:** 24
- **Evaluation Metric Top-K:** 5

## Summary Table per Category

| Category | Queries | Temporal Precision | Precision@5 | Grounding Rate | Refusal Recall (Should Refuse) | False Refusal Rate (Non-Refuse) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Ambiguous** | 6 | 100.0% (1/6) | 83.3% (6/6) | 100.0% (6/6) | 100.0% (6/6) | N/A |
| **Hybrid** | 6 | 68.3% (6/6) | 46.7% (6/6) | 100.0% (6/6) | N/A | 0.0% (0/6) |
| **Semantic** | 6 | N/A | 6.7% (6/6) | 100.0% (6/6) | N/A | 0.0% (0/6) |
| **Temporal** | 6 | 83.3% (6/6) | 36.7% (6/6) | 57.0% (6/6) | N/A | 16.7% (1/6) |
| **Overall** | **24** | **77.7% (13/24)** | **43.3% (24/24)** | **89.3% (24/24)** | **100.0% (6/6)** | **5.6% (1/18)** |

## Episode & System Efficiency Metrics (Chunk 2)

| Metric | Value |
|---|:---:|
| **Database Compression Ratio (Captures ÷ Episodes)** | 1.39x |
| **Mean Distinct Episodes @ 5** | 3.75 / 5 |
| **Mean Context Characters per Query** | 2818.2 chars |
| **Mean Query Latency** | 25.9 ms |

## Delta Comparison vs `episodes`

| Metric | `episodes` | `grounded` | Delta (Δ) |
|---|:---:|:---:|:---:|
| **Temporal Precision** | 85.4% | 77.7% | **-7.7%** |
| **Precision@5** | 40.0% | 43.3% | **+3.3%** |
| **Grounding Rate** | 27.1% | 89.3% | **+62.2%** |
| **Refusal Recall (Should Refuse)** | 50.0% | 100.0% | **+50.0%** |
| **False Refusal Rate (Non-Refuse)** | 0.0% | 5.6% | **+5.6%** |

## Detailed Query Breakdown

| ID | Category | Query | Temp Prec | P@5 | Grounding | Refused? | Should Refuse? | Reason |
|---|---|---|:---:|:---:|:---:|:---:|:---:|---|
| T1 | temporal | What was I doing at 9:50 PM on November 23? | 100.0% | 0.0% | 100.0% | No | No | — |
| T2 | temporal | What apps did I use between 9:40 PM and 10:00 PM on November 23? | 100.0% | 20.0% | 92.3% | No | No | — |
| T3 | temporal | What was I doing between 9:42 PM and 9:46 PM on November 23? | 0.0% | 0.0% | 100.0% | Yes | No | low_confidence_similarity |
| T4 | temporal | How long did I spend on Chrome between 9:40 PM and 9:50 PM on November 23? | 100.0% | 100.0% | 50.0% | No | No | — |
| T5 | temporal | What was the last thing I was doing on November 23? | 100.0% | 100.0% | 0.0% | No | No | — |
| T6 | temporal | When did I start working on November 23? | 100.0% | 0.0% | 0.0% | No | No | — |
| S1 | semantic | Find captures where requirements.txt was open in the editor | N/A | 40.0% | 100.0% | No | No | — |
| S2 | semantic | Where did I see the word 'WhatsApp'? | N/A | 0.0% | 100.0% | No | No | — |
| S3 | semantic | What was I reading about major project thesis? | N/A | 0.0% | 100.0% | No | No | — |
| S4 | semantic | Which files was I editing in Antigravity IDE? | N/A | 0.0% | 100.0% | No | No | — |
| S5 | semantic | What websites was I visiting on Google Chrome? | N/A | 0.0% | 100.0% | No | No | — |
| S6 | semantic | Find where I was looking at query_taxonomy.json | N/A | 0.0% | 100.0% | No | No | — |
| H1 | hybrid | What repo documentation was I reading around 9:53 PM on November 23? | 100.0% | 60.0% | 100.0% | No | No | — |
| H2 | hybrid | What Claude conversation was I having in Chrome around 9:45 PM on November 23? | 50.0% | 0.0% | 100.0% | No | No | — |
| H3 | hybrid | What search query did I perform in Chrome around 9:43 PM on November 23? | 20.0% | 0.0% | 100.0% | No | No | — |
| H4 | hybrid | What file was open in Antigravity IDE between 9:42 PM and 9:45 PM on November 23? | 100.0% | 40.0% | 100.0% | No | No | — |
| H5 | hybrid | Did I look at WhatsApp around 9:51 PM on November 23? | 40.0% | 80.0% | 100.0% | No | No | — |
| H6 | hybrid | Summarize what I did with Agent_Context.md between 9:50 PM and 9:56 PM on November 23 | 100.0% | 100.0% | 100.0% | No | No | — |
| A1 | ambiguous | What did my colleague say about the project deadline on the call? | N/A | 100.0% | 100.0% | Yes | Yes | modality_unsupported_no_audio |
| A2 | ambiguous | What was I working on three months ago on August 15th? | 100.0% | 100.0% | 100.0% | Yes | Yes | no_data_in_range |
| A3 | ambiguous | Why was I reading WhatsApp messages at 9:50 PM? | N/A | 0.0% | 100.0% | Yes | Yes | unobservable_internal_intent |
| A4 | ambiguous | What will I be coding tomorrow morning at 10 AM? | N/A | 100.0% | 100.0% | Yes | Yes | future_time |
| A5 | ambiguous | Did I finish all tasks planned for next month? | N/A | 100.0% | 100.0% | Yes | Yes | future_time |
| A6 | ambiguous | What was displayed on my secondary screen when the power fluctuated? | N/A | 100.0% | 100.0% | Yes | Yes | unobservable_physical_event |