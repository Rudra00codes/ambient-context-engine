"""
Tests for Chunk 5:
- Hit@k and MRR metric calculations
- Empty/generic residual query detection for skipping similarity floor
- answer_source taxonomy (refusal_gate, aggregate_operator, template_fallback, llm)
- Strict eval abort when Ollama is unreachable and ALLOW_TEMPLATE_FALLBACK is False
"""

import os
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from storage.db import DatabaseManager
from processing.embed import EmbeddingGenerator
from intelligence.rag import RAGAgent
from intelligence.grounding import is_generic_or_empty_query, check_pregeneration_refusals
from evaluation.run_eval import compute_hit_at_k, compute_mrr, compute_precision_at_k


class TestChunk5Metrics(unittest.TestCase):
    def test_generic_or_empty_query(self):
        # Empty or whitespace queries
        self.assertTrue(is_generic_or_empty_query(""))
        self.assertTrue(is_generic_or_empty_query("   "))
        self.assertTrue(is_generic_or_empty_query(None))

        # Generic activity phrases
        self.assertTrue(is_generic_or_empty_query("what was I doing"))
        self.assertTrue(is_generic_or_empty_query("doing"))
        self.assertTrue(is_generic_or_empty_query("working on"))
        self.assertTrue(is_generic_or_empty_query("active activity"))
        self.assertTrue(is_generic_or_empty_query("show me my tasks"))

        # Specific queries containing substantive keywords
        self.assertFalse(is_generic_or_empty_query("editing requirements.txt"))
        self.assertFalse(is_generic_or_empty_query("database schema"))
        self.assertFalse(is_generic_or_empty_query("Chrome WhatsApp"))
        self.assertFalse(is_generic_or_empty_query("reading thesis draft"))

    def test_compute_hit_at_k(self):
        sources = [
            {"id": 10, "source": "screen"},
            {"id": 20, "source": "screen"},
            {"id": 30, "source": "screen"},
            {"id": 40, "source": "screen"},
            {"id": 50, "source": "screen"},
            {"id": 60, "source": "screen"},
        ]

        # Match at rank 1
        self.assertEqual(compute_hit_at_k(sources, [10], k=5, should_refuse=False, is_refusal=False), 1.0)
        # Match at rank 5
        self.assertEqual(compute_hit_at_k(sources, [50], k=5, should_refuse=False, is_refusal=False), 1.0)
        # Match at rank 6 (outside top-5) -> 0.0
        self.assertEqual(compute_hit_at_k(sources, [60], k=5, should_refuse=False, is_refusal=False), 0.0)
        # No match anywhere
        self.assertEqual(compute_hit_at_k(sources, [999], k=5, should_refuse=False, is_refusal=False), 0.0)

        # Episode capture_ids match
        ep_sources = [
            {"id": 1, "source": "episode", "capture_ids": [101, 102, 103]},
            {"id": 2, "source": "episode", "capture_ids": [201, 202]},
        ]
        self.assertEqual(compute_hit_at_k(ep_sources, [102], k=5, should_refuse=False, is_refusal=False), 1.0)
        self.assertEqual(compute_hit_at_k(ep_sources, [999], k=5, should_refuse=False, is_refusal=False), 0.0)

        # Refusal query
        self.assertEqual(compute_hit_at_k([], [], k=5, should_refuse=True, is_refusal=True), 1.0)
        self.assertEqual(compute_hit_at_k(sources, [], k=5, should_refuse=True, is_refusal=False), 0.0)

    def test_compute_mrr(self):
        sources = [
            {"id": 10, "source": "screen"},
            {"id": 20, "source": "screen"},
            {"id": 30, "source": "screen"},
            {"id": 40, "source": "screen"},
        ]

        # First match at rank 1 -> RR = 1.0
        self.assertEqual(compute_mrr(sources, [10, 30], should_refuse=False, is_refusal=False), 1.0)
        # First match at rank 2 -> RR = 0.5
        self.assertEqual(compute_mrr(sources, [20, 30], should_refuse=False, is_refusal=False), 0.5)
        # First match at rank 4 -> RR = 0.25
        self.assertEqual(compute_mrr(sources, [40], should_refuse=False, is_refusal=False), 0.25)
        # No match -> RR = 0.0
        self.assertEqual(compute_mrr(sources, [999], should_refuse=False, is_refusal=False), 0.0)

        # Refusal queries
        self.assertEqual(compute_mrr([], [], should_refuse=True, is_refusal=True), 1.0)
        self.assertEqual(compute_mrr(sources, [], should_refuse=True, is_refusal=False), 0.0)


class TestChunk5AnswerSourceAndStrictFallback(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test.db")
        self.db = DatabaseManager(self.db_path)
        self.embedder = EmbeddingGenerator()

        # Insert some test captures
        emb = self.embedder.generate("VS Code editing python file")
        self.db.insert_capture(
            source="screen",
            text_content="def solve(): pass",
            embedding=emb,
            window_title="main.py - VS Code",
            process_name="Code.exe",
            timestamp="2026-11-23T14:30:00",
        )
        self.rag = RAGAgent(self.db, self.embedder)

    def tearDown(self):
        self.db.close()
        self.tmp_dir.cleanup()

    def test_answer_source_future_refusal(self):
        res = self.rag.query("What will I be doing tomorrow?", reference_now="2026-11-23T15:00:00")
        self.assertEqual(res.get("answer_source"), "refusal_gate")
        self.assertTrue(res.get("refused"))

    def test_answer_source_aggregate_operator(self):
        res = self.rag.query(
            "What apps did I use between 2 PM and 3 PM on November 23?",
            reference_now="2026-11-23T16:00:00",
        )
        self.assertEqual(res.get("answer_source"), "aggregate_operator")

    def test_answer_source_modality_refusal(self):
        res = self.rag.query("What was said on the call at 2:30 PM?", reference_now="2026-11-23T16:00:00")
        self.assertEqual(res.get("answer_source"), "refusal_gate")
        self.assertTrue(res.get("refused"))

    def test_strict_eval_aborts_when_ollama_unreachable(self):
        import requests
        old_env = os.environ.get("ALLOW_TEMPLATE_FALLBACK")
        os.environ["ALLOW_TEMPLATE_FALLBACK"] = "false"

        try:
            with patch("requests.post", side_effect=requests.ConnectionError("Connection refused")):
                with self.assertRaises(RuntimeError) as ctx:
                    # "main.py" has exact keyword match in test DB, so it passes pregeneration gate and calls Ollama
                    self.rag.query("main.py", reference_now="2026-11-23T16:00:00")
                self.assertIn("ALLOW_TEMPLATE_FALLBACK is False", str(ctx.exception))
        finally:
            if old_env is None:
                os.environ.pop("ALLOW_TEMPLATE_FALLBACK", None)
            else:
                os.environ["ALLOW_TEMPLATE_FALLBACK"] = old_env


if __name__ == "__main__":
    unittest.main()
