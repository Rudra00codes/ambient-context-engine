"""
Unit Tests for Temporal Decomposition & Parsing Logic — tests/test_temporal.py
"""

import unittest
from datetime import datetime, date, time as dtime

from intelligence.temporal import parse_temporal, TemporalParse, _parse_clock_time
from storage.db import _fts_query


class TestTemporalParser(unittest.TestCase):
    def setUp(self):
        # Reference datetime matching evaluation dataset: Nov 23, 2026, 22:05:00
        self.ref_now = datetime(2026, 11, 23, 22, 5, 0)

    # ─── Clock Time Tests ────────────────────────────────────────────
    def test_clock_time_12h_standard(self):
        t = _parse_clock_time("3pm")
        self.assertEqual(t, dtime(15, 0))

        t2 = _parse_clock_time("3:15 PM")
        self.assertEqual(t2, dtime(15, 15))

        t3 = _parse_clock_time("10:00 AM")
        self.assertEqual(t3, dtime(10, 0))

    def test_clock_time_colonless(self):
        t1 = _parse_clock_time("950 PM")
        self.assertEqual(t1, dtime(21, 50))

        t2 = _parse_clock_time("1000 PM")
        self.assertEqual(t2, dtime(22, 0))

        t3 = _parse_clock_time("415 PM")
        self.assertEqual(t3, dtime(16, 15))

    def test_clock_time_24h(self):
        t = _parse_clock_time("15:15")
        self.assertEqual(t, dtime(15, 15))

    # ─── Date & Day-part Tests ───────────────────────────────────────
    def test_explicit_date_with_and_without_year(self):
        p1 = parse_temporal("What was I doing on September 5th?", now=self.ref_now)
        self.assertTrue(p1.start.startswith("2026-09-05T00:00:00"))
        self.assertTrue(p1.end.startswith("2026-09-05T23:59:59"))

        p2 = parse_temporal("What was I doing on August 15th 2026?", now=self.ref_now)
        self.assertTrue(p2.start.startswith("2026-08-15T00:00:00"))

    def test_relative_date_today_yesterday_last_night(self):
        p_today = parse_temporal("What was I doing today?", now=self.ref_now)
        self.assertTrue(p_today.start.startswith("2026-11-23T00:00:00"))

        p_yesterday = parse_temporal("What was I doing yesterday?", now=self.ref_now)
        self.assertTrue(p_yesterday.start.startswith("2026-11-22T00:00:00"))

        p_last_night = parse_temporal("What was I doing last night?", now=self.ref_now)
        self.assertEqual(p_last_night.start, "2026-11-22T21:00:00")
        self.assertEqual(p_last_night.end, "2026-11-23T05:00:00")

    def test_day_parts(self):
        p_morn = parse_temporal("What was I doing this morning?", now=self.ref_now)
        self.assertEqual(p_morn.start, "2026-11-23T05:00:00")
        self.assertEqual(p_morn.end, "2026-11-23T12:00:00")

        p_aft = parse_temporal("What was I doing this afternoon?", now=self.ref_now)
        self.assertEqual(p_aft.start, "2026-11-23T12:00:00")
        self.assertEqual(p_aft.end, "2026-11-23T17:00:00")

        p_eve = parse_temporal("What was I doing this evening?", now=self.ref_now)
        self.assertEqual(p_eve.start, "2026-11-23T17:00:00")
        self.assertEqual(p_eve.end, "2026-11-23T21:00:00")

    def test_relative_offsets(self):
        p_offset = parse_temporal("What was I doing three months ago?", now=self.ref_now)
        self.assertIsNotNone(p_offset.start)
        self.assertTrue("2026-08" in p_offset.start)

    def test_future_expressions(self):
        p_tomorrow = parse_temporal("What will I be coding tomorrow morning at 10 AM?", now=self.ref_now)
        self.assertTrue(p_tomorrow.is_future)

        p_next_month = parse_temporal("Did I finish all tasks planned for next month?", now=self.ref_now)
        self.assertTrue(p_next_month.is_future)

    # ─── Intent Detection Tests ──────────────────────────────────────
    def test_intents(self):
        p_apps = parse_temporal("What apps did I use between 940 PM and 1000 PM on November 23?", now=self.ref_now)
        self.assertEqual(p_apps.intent, "apps")

        p_dur = parse_temporal("How long did I spend on Chrome between 940 PM and 950 PM?", now=self.ref_now)
        self.assertEqual(p_dur.intent, "duration")

        p_lat = parse_temporal("What was the last thing I was doing yesterday?", now=self.ref_now)
        self.assertEqual(p_lat.intent, "latest")

        p_ear = parse_temporal("When did I start working on September 5th?", now=self.ref_now)
        self.assertEqual(p_ear.intent, "earliest")

        p_search = parse_temporal("Find where I was looking at query_taxonomy.json", now=self.ref_now)
        self.assertEqual(p_search.intent, "search")

    # ─── FTS Query Helper Tests ──────────────────────────────────────
    def test_fts_query_sanitization(self):
        res1 = _fts_query("requirements.txt")
        self.assertEqual(res1, '"requirements" OR "txt"')

        res2 = _fts_query("Where did I see the word 'WhatsApp'?")
        self.assertEqual(res2, '"see" OR "word" OR "whatsapp"')

        res3 = _fts_query("what was i doing?")
        # Stopwords stripped
        self.assertIsNone(res3)

    # ─── Evaluation Queries (All 24) ─────────────────────────────────
    def test_eval_query_T1(self):
        p = parse_temporal("What was I doing at 9:50 PM on November 23?", now=self.ref_now)
        self.assertEqual(p.start, "2026-11-23T21:35:00")
        self.assertEqual(p.end, "2026-11-23T22:05:00")
        self.assertFalse(p.is_future)

    def test_eval_query_T2(self):
        p = parse_temporal("What apps did I use between 9:40 PM and 10:00 PM on November 23?", now=self.ref_now)
        self.assertEqual(p.start, "2026-11-23T21:40:00")
        self.assertEqual(p.end, "2026-11-23T22:00:00")
        self.assertEqual(p.intent, "apps")

    def test_eval_query_T3(self):
        p = parse_temporal("What was I doing between 9:42 PM and 9:46 PM on November 23?", now=self.ref_now)
        self.assertEqual(p.start, "2026-11-23T21:42:00")
        self.assertEqual(p.end, "2026-11-23T21:46:00")

    def test_eval_query_T4(self):
        p = parse_temporal("How long did I spend on Chrome between 9:40 PM and 9:50 PM on November 23?", now=self.ref_now)
        self.assertEqual(p.start, "2026-11-23T21:40:00")
        self.assertEqual(p.end, "2026-11-23T21:50:00")
        self.assertEqual(p.intent, "duration")
        self.assertIn("chrome", p.residual_query.lower())

    def test_eval_query_T5(self):
        p = parse_temporal("What was the last thing I was doing on November 23?", now=self.ref_now)
        self.assertEqual(p.intent, "latest")
        self.assertEqual(p.start, "2026-11-23T00:00:00")
        self.assertEqual(p.end, "2026-11-23T22:05:00")

    def test_eval_query_T6(self):
        p = parse_temporal("When did I start working on November 23?", now=self.ref_now)
        self.assertEqual(p.intent, "earliest")
        self.assertEqual(p.start, "2026-11-23T00:00:00")
        self.assertEqual(p.end, "2026-11-23T22:05:00")

    def test_eval_query_S1(self):
        p = parse_temporal("Find captures where requirements.txt was open in the editor", now=self.ref_now)
        self.assertIsNone(p.start)
        self.assertIn("requirements.txt", p.residual_query)

    def test_eval_query_S2(self):
        p = parse_temporal("Where did I see the word 'WhatsApp'?", now=self.ref_now)
        self.assertIsNone(p.start)
        self.assertIn("whatsapp", p.residual_query.lower())

    def test_eval_query_S3(self):
        p = parse_temporal("What was I reading about major project thesis?", now=self.ref_now)
        self.assertIsNone(p.start)
        self.assertIn("major project thesis", p.residual_query.lower())

    def test_eval_query_S4(self):
        p = parse_temporal("Which files was I editing in Antigravity IDE?", now=self.ref_now)
        self.assertIsNone(p.start)
        self.assertIn("antigravity ide", p.residual_query.lower())

    def test_eval_query_S5(self):
        p = parse_temporal("What websites was I visiting on Google Chrome?", now=self.ref_now)
        self.assertIsNone(p.start)
        self.assertIn("google chrome", p.residual_query.lower())

    def test_eval_query_S6(self):
        p = parse_temporal("Find where I was looking at query_taxonomy.json", now=self.ref_now)
        self.assertIsNone(p.start)
        self.assertIn("query_taxonomy.json", p.residual_query)

    def test_eval_query_H1(self):
        p = parse_temporal("What repo documentation was I reading around 9:53 PM on November 23?", now=self.ref_now)
        self.assertEqual(p.start, "2026-11-23T21:38:00")
        self.assertEqual(p.end, "2026-11-23T22:08:00")
        self.assertIn("repo documentation", p.residual_query)

    def test_eval_query_H2(self):
        p = parse_temporal("What Claude conversation was I having in Chrome around 9:45 PM on November 23?", now=self.ref_now)
        self.assertEqual(p.start, "2026-11-23T21:30:00")
        self.assertEqual(p.end, "2026-11-23T22:00:00")
        self.assertIn("claude", p.residual_query.lower())

    def test_eval_query_H3(self):
        p = parse_temporal("What search query did I perform in Chrome around 9:43 PM on November 23?", now=self.ref_now)
        self.assertEqual(p.start, "2026-11-23T21:28:00")
        self.assertEqual(p.end, "2026-11-23T21:58:00")
        self.assertIn("search query", p.residual_query.lower())

    def test_eval_query_H4(self):
        p = parse_temporal("What file was open in Antigravity IDE between 9:42 PM and 9:45 PM on November 23?", now=self.ref_now)
        self.assertEqual(p.start, "2026-11-23T21:42:00")
        self.assertEqual(p.end, "2026-11-23T21:45:00")
        self.assertIn("file", p.residual_query.lower())

    def test_eval_query_H5(self):
        p = parse_temporal("Did I look at WhatsApp around 9:51 PM on November 23?", now=self.ref_now)
        self.assertEqual(p.start, "2026-11-23T21:36:00")
        self.assertEqual(p.end, "2026-11-23T22:06:00")
        self.assertIn("whatsapp", p.residual_query.lower())

    def test_eval_query_H6(self):
        p = parse_temporal("Summarize what I did with Agent_Context.md between 9:50 PM and 9:56 PM on November 23", now=self.ref_now)
        self.assertEqual(p.start, "2026-11-23T21:50:00")
        self.assertEqual(p.end, "2026-11-23T21:56:00")
        self.assertIn("agent_context.md", p.residual_query.lower())

    def test_eval_query_A1(self):
        p = parse_temporal("What did my colleague say about the project deadline on the call?", now=self.ref_now)
        self.assertIsNone(p.start)

    def test_eval_query_A2(self):
        p = parse_temporal("What was I working on three months ago on August 15th?", now=self.ref_now)
        self.assertTrue(p.start.startswith("2026-08-15T00:00:00"))

    def test_eval_query_A3(self):
        p = parse_temporal("Why was I reading WhatsApp messages at 9:50 PM?", now=self.ref_now)
        self.assertEqual(p.start, "2026-11-23T21:35:00")

    def test_eval_query_A4(self):
        p = parse_temporal("What will I be coding tomorrow morning at 10 AM?", now=self.ref_now)
        self.assertTrue(p.is_future)

    def test_eval_query_A5(self):
        p = parse_temporal("Did I finish all tasks planned for next month?", now=self.ref_now)
        self.assertTrue(p.is_future)

    def test_eval_query_A6(self):
        p = parse_temporal("What was displayed on my secondary screen when the power fluctuated?", now=self.ref_now)
        self.assertIsNone(p.start)


if __name__ == "__main__":
    unittest.main()
