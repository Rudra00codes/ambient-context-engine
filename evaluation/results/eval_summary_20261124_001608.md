# OmniContext Evaluation Results — Tag: `baseline`

- **Run Tag:** `baseline`
- **Timestamp:** `20261124_001608`
- **Database Snapshot:** `X:\InternProject\ambient-context-engine\data\context.db`
- **Reference Now:** `2026-11-23T22:05:00`
- **Queries Evaluated:** 24
- **Evaluation Metric Top-K:** 5

## Summary Table per Category

| Category | Queries | Temporal Precision | Precision@5 | Grounding Rate | Refusal Recall (Should Refuse) | False Refusal Rate (Non-Refuse) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Ambiguous** | 6 | 0.0% (1/6) | 0.0% (6/6) | 0.0% (6/6) | 0.0% (0/6) | N/A |
| **Hybrid** | 6 | 0.0% (6/6) | 0.0% (6/6) | 0.0% (6/6) | N/A | 0.0% (0/6) |
| **Semantic** | 6 | N/A | 0.0% (6/6) | 0.0% (6/6) | N/A | 0.0% (0/6) |
| **Temporal** | 6 | 10.0% (6/6) | 3.3% (6/6) | 0.0% (6/6) | N/A | 0.0% (0/6) |
| **Overall** | **24** | **4.6% (13/24)** | **0.8% (24/24)** | **0.0% (24/24)** | **0.0% (0/6)** | **0.0% (0/18)** |

## Detailed Query Breakdown

| ID | Category | Query | Temp Prec | P@5 | Grounding | Refused? | Should Refuse? | Reason |
|---|---|---|:---:|:---:|:---:|:---:|:---:|---|
| T1 | temporal | What was I doing at 9:50 PM on November 23? | 20.0% | 0.0% | 0.0% | No | No | — |
| T2 | temporal | What apps did I use between 9:40 PM and 10:00 PM on November 23? | 0.0% | 0.0% | 0.0% | No | No | — |
| T3 | temporal | What was I doing between 9:42 PM and 9:46 PM on November 23? | 10.0% | 20.0% | 0.0% | No | No | — |
| T4 | temporal | How long did I spend on Chrome between 9:40 PM and 9:50 PM on November 23? | 0.0% | 0.0% | 0.0% | No | No | — |
| T5 | temporal | What was the last thing I was doing on November 23? | 30.0% | 0.0% | 0.0% | No | No | — |
| T6 | temporal | When did I start working on November 23? | 0.0% | 0.0% | 0.0% | No | No | — |
| S1 | semantic | Find captures where requirements.txt was open in the editor | N/A | 0.0% | 0.0% | No | No | — |
| S2 | semantic | Where did I see the word 'WhatsApp'? | N/A | 0.0% | 0.0% | No | No | — |
| S3 | semantic | What was I reading about major project thesis? | N/A | 0.0% | 0.0% | No | No | — |
| S4 | semantic | Which files was I editing in Antigravity IDE? | N/A | 0.0% | 0.0% | No | No | — |
| S5 | semantic | What websites was I visiting on Google Chrome? | N/A | 0.0% | 0.0% | No | No | — |
| S6 | semantic | Find where I was looking at query_taxonomy.json | N/A | 0.0% | 0.0% | No | No | — |
| H1 | hybrid | What repo documentation was I reading around 9:53 PM on November 23? | 0.0% | 0.0% | 0.0% | No | No | — |
| H2 | hybrid | What Claude conversation was I having in Chrome around 9:45 PM on November 23? | 0.0% | 0.0% | 0.0% | No | No | — |
| H3 | hybrid | What search query did I perform in Chrome around 9:43 PM on November 23? | 0.0% | 0.0% | 0.0% | No | No | — |
| H4 | hybrid | What file was open in Antigravity IDE between 9:42 PM and 9:45 PM on November 23? | 0.0% | 0.0% | 0.0% | No | No | — |
| H5 | hybrid | Did I look at WhatsApp around 9:51 PM on November 23? | 0.0% | 0.0% | 0.0% | No | No | — |
| H6 | hybrid | Summarize what I did with Agent_Context.md between 9:50 PM and 9:56 PM on November 23 | 0.0% | 0.0% | 0.0% | No | No | — |
| A1 | ambiguous | What did my colleague say about the project deadline on the call? | N/A | 0.0% | 0.0% | No | Yes | — |
| A2 | ambiguous | What was I working on three months ago on August 15th? | 0.0% | 0.0% | 0.0% | No | Yes | — |
| A3 | ambiguous | Why was I reading WhatsApp messages at 9:50 PM? | N/A | 0.0% | 0.0% | No | Yes | — |
| A4 | ambiguous | What will I be coding tomorrow morning at 10 AM? | N/A | 0.0% | 0.0% | No | Yes | — |
| A5 | ambiguous | Did I finish all tasks planned for next month? | N/A | 0.0% | 0.0% | No | Yes | — |
| A6 | ambiguous | What was displayed on my secondary screen when the power fluctuated? | N/A | 0.0% | 0.0% | No | Yes | — |