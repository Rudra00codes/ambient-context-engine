"""
Ambient Context Engine — Centralized Configuration

All tunable parameters in one place. Override via environment variables
where noted, otherwise edit this file directly.
"""

import os
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "context.db"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ─── Capture Settings ────────────────────────────────────────────────
CAPTURE_INTERVAL_SECS = 5          # Screen capture frequency (seconds)
AUDIO_CHUNK_SECS = 30              # Audio buffer duration before transcription
AUDIO_SAMPLE_RATE = 16000          # Whisper expects 16kHz mono
FRAME_DIFF_THRESHOLD = 500         # Min changed pixels to trigger OCR

# ─── OCR Settings ────────────────────────────────────────────────────
TESSERACT_CMD = os.environ.get(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
TESSERACT_LANG = "eng"
TESSERACT_PSM = 6                  # Page segmentation mode: block of text
TESSERACT_OEM = 3                  # LSTM engine mode

# ─── Nudge Settings ──────────────────────────────────────────────────
NUDGE_INTERVAL_MINUTES = 60

# ─── Whisper Settings ────────────────────────────────────────────────
WHISPER_MODEL = "base"             # tiny | base | small | medium
WHISPER_LANGUAGE = "en"           # language code (openai-whisper)

# ─── Embedding Settings ─────────────────────────────────────────────
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384                # Output dimension of all-MiniLM-L6-v2

# ─── Ollama / LLM Settings ──────────────────────────────────────────
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = "llama3.2:3b"
LLM_CONTEXT_MAX_CHARS = 6000      # Max chars of retrieved context to send to LLM

# ─── RAG Search Settings ────────────────────────────────────────────
SEARCH_TOP_K = 10                  # Number of results for semantic/keyword search
RRF_K = 60                        # Reciprocal Rank Fusion constant

# ─── Storage / Retention ─────────────────────────────────────────────
RETENTION_DAYS = 30                # Auto-delete captures older than this (0 = keep forever)

# ─── Deduplication ───────────────────────────────────────────────────
OCR_DEDUP_SIMILARITY = 0.90       # SequenceMatcher ratio threshold to skip duplicate OCR
OCR_DEDUP_HISTORY = 5             # Number of recent OCR texts to compare against

# ─── Feature Flags (Ablation Study) ──────────────────────────────────
USE_TEMPORAL = os.environ.get("USE_TEMPORAL", "true").lower() in ("true", "1", "yes")
USE_EPISODES = os.environ.get("USE_EPISODES", "true").lower() in ("true", "1", "yes")
USE_GROUNDING = os.environ.get("USE_GROUNDING", "true").lower() in ("true", "1", "yes")

# Temporal Decomposition Settings
AROUND_WINDOW_MINUTES = int(os.environ.get("AROUND_WINDOW_MINUTES", "15"))

# Episode Segmentation Settings (Chunk 2)
EPISODE_MAX_GAP_SECS = int(os.environ.get("EPISODE_MAX_GAP_SECS", "120"))
EPISODE_SIM_THRESHOLD = float(os.environ.get("EPISODE_SIM_THRESHOLD", "0.85"))
EPISODE_REPRESENTATIVE_MAX_CHARS = int(os.environ.get("EPISODE_REPRESENTATIVE_MAX_CHARS", "1000"))

# Grounded Generation & Refusal Gate Settings (Chunk 3)
REFUSAL_SIM_FLOOR = float(os.environ.get("REFUSAL_SIM_FLOOR", "0.35"))
GROUNDING_MIN = float(os.environ.get("GROUNDING_MIN", "0.60"))
CITATION_TOLERANCE_MINUTES = int(os.environ.get("CITATION_TOLERANCE_MINUTES", "2"))

# ─── Logging ─────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
