"""
Unit Tests for Interface API Endpoints (Flask REST API)
Tests all routes: status, episodes, activity, recap, search, nudge, settings, and chat.
"""

import unittest
import json
import os

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import interface.app as ia


class TestInterfaceAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = ia.app.test_client()

    def test_root_index(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Ambient Context Engine", res.data)

    def test_api_status(self):
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "online")
        self.assertTrue(data.get("offline_mode"))
        self.assertTrue(data.get("zero_telemetry"))
        self.assertIn("total_captures", data)
        self.assertIn("total_episodes", data)

    def test_api_stats(self):
        res = self.client.get("/api/stats")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("total_captures", data)
        self.assertIn("db_size_mb", data)

    def test_api_episodes(self):
        res = self.client.get("/api/episodes?limit=5")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("episodes", data)
        self.assertIn("total", data)
        self.assertIn("processes", data)
        if data["episodes"]:
            ep = data["episodes"][0]
            self.assertIn("id", ep)
            self.assertIn("dominant_title", ep)
            self.assertIn("duration_formatted", ep)

    def test_api_episode_detail(self):
        res = self.client.get("/api/episodes?limit=1")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        if data["episodes"]:
            ep_id = data["episodes"][0]["id"]
            res_det = self.client.get(f"/api/episodes/{ep_id}")
            self.assertEqual(res_det.status_code, 200)
            det_data = res_det.get_json()
            self.assertIn("episode", det_data)
            self.assertIn("captures", det_data)

    def test_api_activity(self):
        res = self.client.get("/api/activity")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("total_active_formatted", data)
        self.assertIn("app_breakdown", data)
        self.assertIn("hourly_distribution", data)
        self.assertEqual(len(data["hourly_distribution"]), 24)

    def test_api_recap(self):
        res = self.client.get("/api/recap")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("summary", data)
        self.assertIn("total_time", data)

    def test_api_search(self):
        res = self.client.get("/api/search?q=test")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("episodes", data)
        self.assertIn("captures", data)

    def test_api_nudge(self):
        res = self.client.get("/api/nudge")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("nudge", data)

    def test_api_settings(self):
        # GET
        res = self.client.get("/api/settings")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("use_temporal", data)
        self.assertIn("use_episodes", data)
        self.assertIn("use_grounding", data)

        # POST update
        res_post = self.client.post("/api/settings", json={"use_temporal": True})
        self.assertEqual(res_post.status_code, 200)
        self.assertTrue(res_post.get_json()["use_temporal"])

    def test_api_chat(self):
        res = self.client.post("/api/chat", json={"question": "What was I coding in Antigravity IDE?", "top_k": 5})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("answer", data)
        self.assertIn("sources", data)
        self.assertIn("grounding_rate", data)
        self.assertFalse(data.get("refused"))

    def test_api_capture_now(self):
        res = self.client.post("/api/capture_now")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("id", data)
        self.assertIn("timestamp", data)


if __name__ == "__main__":
    unittest.main()
