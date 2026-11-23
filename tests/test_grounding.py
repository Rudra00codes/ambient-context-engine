"""
Unit tests for Grounded Generation, Post-hoc Verifier, and Refusal Gates (Chunk 3)
"""

import tempfile
import unittest
from datetime import datetime, time as dtime
from pathlib import Path
import numpy as np

from intelligence.grounding import (
    split_sentences,
    extract_citations,
    parse_sentence_times,
    verify_grounding,
    check_pregeneration_refusals,
    synthesize_grounded_answer,
    GroundingResult,
)
from storage.db import DatabaseManager


class TestGroundingLogic(unittest.TestCase):
    """Tests for sentence splitting, citation parsing, and timestamp validation."""

    def test_split_sentences(self):
        text = "Working on Code.exe [E1]. Then switched to Chrome at 9:50 PM [E2]! Finished reviewing PR [E3]."
        sentences = split_sentences(text)
        self.assertEqual(len(sentences), 3)
        self.assertIn("Working on Code.exe [E1].", sentences)
        self.assertIn("Then switched to Chrome at 9:50 PM [E2]!", sentences)
        self.assertIn("Finished reviewing PR [E3].", sentences)

    def test_split_sentences_with_newlines(self):
        text = "Sentence one [E1].\nSentence two [E2].\n\nSentence three [E3]."
        sentences = split_sentences(text)
        self.assertEqual(len(sentences), 3)

    def test_extract_citations(self):
        s1 = "Activity in VS Code [E12] and Chrome [E15]."
        self.assertEqual(extract_citations(s1), {12, 15})

        s2 = "Single capture reference [C104]."
        self.assertEqual(extract_citations(s2), {104})

        s3 = "Bracketed numeric citation [42]."
        self.assertEqual(extract_citations(s3), {42})

        s4 = "No citation in this claim."
        self.assertEqual(extract_citations(s4), set())

    def test_parse_sentence_times(self):
        # 12-hour format with meridiem
        times1 = parse_sentence_times("At 9:50 PM you opened WhatsApp.")
        self.assertEqual(len(times1), 1)
        self.assertEqual(times1[0], dtime(21, 50))

        times2 = parse_sentence_times("Meeting started at 10:15 am and ended at 11:30 AM.")
        self.assertEqual(len(times2), 2)
        self.assertEqual(times2[0], dtime(10, 15))
        self.assertEqual(times2[1], dtime(11, 30))

        # 24-hour format
        times3 = parse_sentence_times("Logged activity at 21:42 in Code.exe.")
        self.assertEqual(len(times3), 1)
        self.assertEqual(times3[0], dtime(21, 42))

        # No timestamps
        times4 = parse_sentence_times("Viewing requirements.txt in editor.")
        self.assertEqual(len(times4), 0)


class TestPostHocVerifier(unittest.TestCase):
    """Tests for post-hoc verifier and grounding score calculation."""

    def setUp(self):
        self.sources = [
            {
                "id": 1,
                "episode_id": 1,
                "source": "episode",
                "start_time": "2026-11-23T21:40:00",
                "end_time": "2026-11-23T21:45:00",
                "process_name": "chrome.exe",
                "dominant_title": "Claude - Google Chrome",
            },
            {
                "id": 2,
                "episode_id": 2,
                "source": "episode",
                "start_time": "2026-11-23T21:46:00",
                "end_time": "2026-11-23T21:55:00",
                "process_name": "Code.exe",
                "dominant_title": "Agent_Context.md - VS Code",
            },
        ]

    def test_fully_grounded_answer(self):
        answer = (
            "At 21:42, you were using Chrome [E1]. "
            "At 21:50, you switched to VS Code to edit Agent_Context.md [E2]."
        )
        res = verify_grounding(answer, self.sources, tolerance_minutes=2, min_grounding=0.60)
        self.assertEqual(res.grounding_rate, 1.0)
        self.assertEqual(res.supported_sentences, 2)
        self.assertEqual(res.total_sentences, 2)
        self.assertFalse(res.partially_verified)
        self.assertEqual(res.verified_answer, answer)

    def test_out_of_interval_timestamp_fails(self):
        # Episode 1 is 21:40 to 21:45 (+2 min tolerance is 21:38 to 21:47). Claim says 21:55!
        answer = "At 21:55, you were using Chrome [E1]."
        res = verify_grounding(answer, self.sources, tolerance_minutes=2, min_grounding=0.60)
        self.assertEqual(res.grounding_rate, 0.0)
        self.assertEqual(res.supported_sentences, 0)
        self.assertTrue(res.partially_verified)

    def test_missing_citation_fails(self):
        answer = "You were coding in Python without citing any episode."
        res = verify_grounding(answer, self.sources, tolerance_minutes=2, min_grounding=0.60)
        self.assertEqual(res.grounding_rate, 0.0)
        self.assertEqual(res.supported_sentences, 0)
        self.assertTrue(res.partially_verified)

    def test_partial_grounding_filter(self):
        answer = (
            "At 21:42, you were using Chrome [E1]. "
            "You were also secretly browsing Twitter on your phone."
        )
        res = verify_grounding(answer, self.sources, tolerance_minutes=2, min_grounding=0.60)
        # 1 supported out of 2 sentences = 0.50 (< 0.60 min)
        self.assertEqual(res.grounding_rate, 0.5)
        self.assertEqual(res.supported_sentences, 1)
        self.assertEqual(res.total_sentences, 2)
        self.assertTrue(res.partially_verified)
        # Unsupported sentence should be filtered out
        self.assertIn("At 21:42, you were using Chrome [E1].", res.verified_answer)
        self.assertNotIn("browsing Twitter", res.verified_answer)
        self.assertIn("[Partially verified from context]", res.verified_answer)

    def test_refusal_is_fully_grounded(self):
        answer = "I cannot predict future activities."
        res = verify_grounding(answer, [], is_refusal=True)
        self.assertEqual(res.grounding_rate, 1.0)
        self.assertFalse(res.partially_verified)


class TestPreGenerationRefusalGates(unittest.TestCase):
    """Tests for pre-generation refusal gates."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(db_path=self.test_db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_modality_check_refuses_when_no_audio(self):
        # Database has screen captures but 0 audio captures
        cur = self.db.conn.cursor()
        cur.execute(
            "INSERT INTO captures (timestamp, source, text_content) VALUES ('2026-11-23T10:00:00', 'screen', 'code')"
        )
        self.db.conn.commit()

        q = "What did my colleague say about the deadline on the call?"
        refusal = check_pregeneration_refusals(q, self.db, sources=[])
        self.assertIsNotNone(refusal)
        self.assertTrue(refusal["refused"])
        self.assertEqual(refusal["refusal_reason"], "modality_unsupported_no_audio")
        self.assertIn("no audio transcripts or call recordings", refusal["answer"])

    def test_motive_gate_hedges_screen_state(self):
        q = "Why was I reading WhatsApp messages at 9:50 PM?"
        sources = [{
            "id": 12,
            "source": "episode",
            "start_time": "2026-11-23T21:50:00",
            "dominant_title": "WhatsApp - Google Chrome",
            "process_name": "chrome.exe",
        }]
        refusal = check_pregeneration_refusals(q, self.db, sources=sources)
        self.assertIsNotNone(refusal)
        self.assertTrue(refusal["refused"])
        self.assertEqual(refusal["refusal_reason"], "unobservable_internal_intent")
        self.assertIn("WhatsApp", refusal["answer"])
        self.assertIn("[E12]", refusal["answer"])
        self.assertIn("cannot be determined from screen captures", refusal["answer"])

    def test_unobservable_physical_event_gate(self):
        q = "What was displayed on my secondary screen when the power fluctuated?"
        refusal = check_pregeneration_refusals(q, self.db, sources=[])
        self.assertIsNotNone(refusal)
        self.assertTrue(refusal["refused"])
        self.assertEqual(refusal["refusal_reason"], "unobservable_physical_event")
        self.assertIn("power fluctuations", refusal["answer"])

    def test_similarity_floor_gate(self):
        q = "What is the capital of France?"
        # Mock source with very low cosine similarity and no keyword match
        sources = [{
            "id": 5,
            "source": "episode",
            "cosine_sim": 0.15,
            "keyword_match": False,
        }]
        refusal = check_pregeneration_refusals(q, self.db, sources=sources, sim_floor=0.35)
        self.assertIsNotNone(refusal)
        self.assertTrue(refusal["refused"])
        self.assertEqual(refusal["refusal_reason"], "low_confidence_similarity")

    def test_high_similarity_passes_through(self):
        q = "Which files was I editing in Antigravity IDE?"
        sources = [{
            "id": 3,
            "source": "episode",
            "cosine_sim": 0.65,
            "keyword_match": True,
        }]
        refusal = check_pregeneration_refusals(q, self.db, sources=sources, sim_floor=0.35)
        self.assertIsNone(refusal)


class TestOfflineGroundedSynthesis(unittest.TestCase):
    """Tests for offline grounded answer synthesis."""

    def test_synthesize_grounded_answer(self):
        sources = [
            {
                "id": 10,
                "episode_id": 10,
                "source": "episode",
                "start_time": "2026-11-23T21:50:00",
                "dominant_title": "Agent_Context.md",
                "process_name": "Code.exe",
            },
            {
                "id": 11,
                "episode_id": 11,
                "source": "episode",
                "start_time": "2026-11-23T21:52:00",
                "dominant_title": "query_taxonomy.json",
                "process_name": "Code.exe",
            },
        ]
        ans = synthesize_grounded_answer("What was I editing?", sources)
        self.assertIn("[E10]", ans)
        self.assertIn("[E11]", ans)
        self.assertIn("Code.exe", ans)
        self.assertIn("21:50", ans)

        # Verify that synthesized answer passes verify_grounding!
        res = verify_grounding(ans, sources, tolerance_minutes=2)
        self.assertEqual(res.grounding_rate, 1.0)
        self.assertFalse(res.partially_verified)


if __name__ == "__main__":
    unittest.main()
