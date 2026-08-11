import unittest

from core.device_view import _merge_device_config, _set_ota_status


class DeviceActionHelpersTests(unittest.TestCase):
    def test_merge_device_config_updates_supported_fields(self):
        item = {}
        config = _merge_device_config(
            item,
            {
                "wifi_ssid": "GardenNet",
                "wifi_password": "secret",
                "report_interval_sec": 120,
                "sleep_mode": True,
                "flow_rate_ml_sec": 20,
            },
        )

        self.assertEqual(config["wifi_ssid"], "GardenNet")
        self.assertEqual(config["report_interval_sec"], 120)
        self.assertTrue(config["sleep_mode"])
        self.assertEqual(config["flow_rate_ml_sec"], 20)
        self.assertEqual(item["device_config"]["wifi_password"], "secret")

    def test_set_ota_status_tracks_state_and_version(self):
        item = {}
        status = _set_ota_status(item, "pending", version="1.2.3", message="Uploading")

        self.assertEqual(status["state"], "pending")
        self.assertEqual(status["version"], "1.2.3")
        self.assertEqual(item["ota_status"]["message"], "Uploading")
        self.assertIn("last_updated_utc", status)


if __name__ == "__main__":
    unittest.main()
