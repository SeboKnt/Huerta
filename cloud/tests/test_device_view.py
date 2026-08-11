import unittest

from core.device_view import (
    _get_alerts,
    _get_device_config,
    _get_irrigation_history,
    _get_ota_status,
    _get_plant_context,
    _get_relay_state,
    _get_stats,
    _get_watering_schedule,
)


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

    def test_irrigation_history_and_config_are_normalized(self):
        item = {
            "irrigation_history": [{"started_at_utc": "2024-01-01T00:00:00Z", "duration_sec": 40}],
            "device_config": {
                "wifi_ssid": "GardenNet",
                "report_interval_sec": 120,
                "watering_duration_sec": 45,
                "sleep_mode": True,
                "wake_interval_sec": 300,
            },
        }
        history = _get_irrigation_history(item)
        config = _get_device_config(item)
        self.assertEqual(len(history), 1)
        self.assertEqual(config["wifi_ssid"], "GardenNet")
        self.assertEqual(config["report_interval_sec"], 120)
        self.assertTrue(config["sleep_mode"])

    def test_ota_status_and_watering_schedule_are_exposed(self):
        item = {
            "ota_status": {"state": "installing", "version": "1.2.3", "message": "Updating"},
            "watering_schedule": {"enabled": True, "interval_hours": 3, "duration_sec": 90, "day": "Monday", "start_time": "14:00"},
        }
        ota_status = _get_ota_status(item)
        schedule = _get_watering_schedule(item)
        self.assertEqual(ota_status["state"], "installing")
        self.assertEqual(schedule["summary"], "Every 3h for 90s; Monday at 14:00")

    def test_plant_context_exposes_room_and_climate(self):
        item = {
            "plant_profile": {
                "plant_name": "Basil",
                "plant_species": "Ocimum basilicum",
                "room": "Kitchen",
                "temperature_c": 24,
                "humidity_pct": 62,
                "soil_moisture_pct": 41,
            }
        }
        context = _get_plant_context(item)
        self.assertEqual(context["plant_name"], "Basil")
        self.assertEqual(context["room"], "Kitchen")
        self.assertEqual(context["temperature_c"], 24)
        self.assertEqual(context["soil_moisture_pct"], 41)


if __name__ == "__main__":
    unittest.main()
