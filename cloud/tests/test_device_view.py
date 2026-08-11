import unittest

from core.device_view import _get_alerts, _get_relay_state, _get_stats


class DeviceViewTests(unittest.TestCase):
    def test_relay_state_uses_explicit_value(self):
        item = {"relay_debug_state": "on"}
        self.assertEqual(_get_relay_state(item), "on")

    def test_alerts_flag_missing_telemetry_and_offline_state(self):
        item = {"last_seen_utc": "", "telemetry_latest": None, "status": "offline"}
        alerts = _get_alerts(item)
        self.assertTrue(any(alert["type"] == "missing_telemetry" for alert in alerts))
        self.assertTrue(any(alert["type"] == "no_recent_contact" for alert in alerts))

    def test_stats_return_expected_summary_fields(self):
        item = {
            "created_at_utc": "2024-01-01T00:00:00Z",
            "last_seen_utc": "2024-01-01T00:00:00Z",
            "telemetry_history": [{"cpu_load_pct": 30}],
        }
        stats = _get_stats(item)
        self.assertIn("uptime_seconds", stats)
        self.assertEqual(stats["telemetry_points"], 1)
        self.assertIn("connected", stats)


if __name__ == "__main__":
    unittest.main()
