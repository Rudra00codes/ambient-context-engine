# OmniContext Model Quantization Benchmark (Chunk 5)

- **Benchmark Timestamp:** `20261126_015623`
- **Database Snapshot:** `context.db`
- **Evaluation Queries:** 24 dev queries
- **Warm-up Discarded:** 1 call per model
- **Ollama Base URL:** `http://127.0.0.1:11434`

## Measured Performance Results

| Model | Measured RAM (GB) | TTFT p50 (ms) | TTFT p95 (ms) | Throughput (tok/s) | p50 E2E Latency (ms) | p95 E2E Latency (ms) | Grounding Rate (%) | Correctness (%) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **`llama3.2:3b-instruct-q4_K_M`** | 2.39 GB | 32.7 ms | 361.6 ms | 63.5 tok/s | 1087.9 ms | 6548.4 ms | 55.2% | 43.5% |

## Model Comparison Summary

| Model | Total Tokens | Mean E2E (ms) | Throughput (tok/s) | Grounding Rate (%) | Correctness (%) |
|---|:---:|:---:|:---:|:---:|:---:|
| **`llama3.2:3b-instruct-q4_K_M`** | 3063 | 2198.7 ms | 63.5 tok/s | 55.2% | 43.5% |
