# Calibration of REFUSAL_SIM_FLOOR (Chunk 3)

Sweeping the similarity floor parameter to optimize refusal recall on ambiguous queries while avoiding false refusals on valid context queries.

| REFUSAL_SIM_FLOOR | Refusal Recall (A1–A6) | False Refusals (18 queries) | False Refusal IDs | Status |
|:---:|:---:|:---:|:---:|:---:|
| 0.20 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.25 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.30 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.35 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.40 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.45 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.50 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.55 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |
| 0.60 | 6/6 (100.0%) | 1/18 (5.6%) | T3 | Eligible |

**Selected Threshold:** `REFUSAL_SIM_FLOOR = 0.35`
- **Refusal Recall:** 100.0% (6/6)
- **False Refusals:** 1/18 (T3, Rate: 5.6%)
- **Justification:** At 0.35, refusal recall on ambiguous questions is maximized (100.0% recall on A1–A6) while allowing at most 1 false refusal (T3, a pure temporal window query with low residual semantic cosine) on the 18 ground-truth activity queries. Consistent with Chunk 3 guidelines requiring <= 1 false refusal.