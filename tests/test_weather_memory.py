import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


class WeatherApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_modules = {
            name: sys.modules.get(name)
            for name in ("urequests", "network", "weather")
        }
        sys.modules["urequests"] = types.ModuleType("urequests")
        sys.modules["network"] = types.ModuleType("network")
        sys.modules["network"].STA_IF = 0
        sys.modules["network"].WLAN = lambda _interface: types.SimpleNamespace(isconnected=lambda: True)
        source = Path(__file__).resolve().parents[1] / "src" / "weather.py"
        spec = importlib.util.spec_from_file_location("weather", source)
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules["weather"] = cls.module
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_forecast_uses_coordinate_endpoint_and_open_meteo_daily_data(self):
        class Response:
            status_code = 200

            def json(self):
                return {
                    "daily": {
                        "time": [
                            "2026-07-17", "2026-07-18", "2026-07-19",
                            "2026-07-20", "2026-07-21",
                        ],
                        "weather_code": [0, 3, 61, 45, 95],
                        "temperature_2m_mean": [30, 31, 29, 28, 27],
                        "precipitation_probability_max": [0, 20, 80, 40, 70],
                    }
                }

            def close(self):
                pass

        original_request = self.module._make_request_with_retry
        requested_urls = []
        try:
            self.module._make_request_with_retry = lambda url: requested_urls.append(url) or Response()

            result = self.module.fetch_weather_forecast(24.6855, 120.8789, days_limit=5)

            self.assertEqual(len(result), 5)
            self.assertEqual(result[0], ("07-17", 30, "Clear", 0))
            self.assertEqual(result[2], ("07-19", 29, "Rain", 80))
            self.assertEqual(result[3][2], "Fog")
            self.assertEqual(result[4][2], "Thunderstorm")
            self.assertIn("latitude=24.6855", requested_urls[0])
            self.assertIn("longitude=120.8789", requested_urls[0])
            self.assertIn("forecast_days=5", requested_urls[0])
            self.assertIn("timezone=Etc/GMT-8", requested_urls[0])
            self.assertNotIn("appid=", requested_urls[0])
        finally:
            self.module._make_request_with_retry = original_request

    def test_current_weather_uses_open_meteo_current_data(self):
        class Response:
            status_code = 200

            def json(self):
                return {"current": {"temperature_2m": 30.5, "weather_code": 2}}

            def close(self):
                pass

        original_request = self.module._make_request_with_retry
        requested_urls = []
        try:
            self.module._make_request_with_retry = lambda url: requested_urls.append(url) or Response()
            result = self.module.fetch_current_weather(24.8138, 120.9675)

            self.assertEqual(result, (30.5, "Clouds"))
            self.assertIn("current=", requested_urls[0])
            self.assertIn("current=temperature_2m,weather_code", requested_urls[0])
            self.assertIn("latitude=24.8138", requested_urls[0])
            self.assertIn("longitude=120.9675", requested_urls[0])
            self.assertIn("timezone=Etc/GMT-8", requested_urls[0])
            self.assertNotIn("appid=", requested_urls[0])
        finally:
            self.module._make_request_with_retry = original_request

    def test_weather_bundle_uses_one_request_for_current_and_forecast(self):
        class Response:
            status_code = 200

            def json(self):
                return {
                    "current": {"temperature_2m": 30.5, "weather_code": 2},
                    "daily": {
                        "time": [
                            "2026-07-17", "2026-07-18", "2026-07-19",
                            "2026-07-20", "2026-07-21",
                        ],
                        "weather_code": [0, 3, 61, 45, 95],
                        "temperature_2m_mean": [30, 31, 29, 28, 27],
                        "precipitation_probability_max": [0, 20, 80, 40, 70],
                    },
                }

            def close(self):
                pass

        original_request = self.module._make_request_with_retry
        requested_urls = []
        try:
            self.module._make_request_with_retry = lambda url: requested_urls.append(url) or Response()

            result = self.module.fetch_weather_bundle(24.6855, 120.8789, days_limit=5)

            self.assertEqual(result[0], (30.5, "Clouds"))
            self.assertEqual(len(result[1]), 5)
            self.assertEqual(len(requested_urls), 1)
            self.assertIn("current=temperature_2m,weather_code", requested_urls[0])
            self.assertIn(
                "daily=weather_code,temperature_2m_mean,precipitation_probability_max",
                requested_urls[0],
            )
            self.assertIn("forecast_days=5", requested_urls[0])
            self.assertIn("timezone=Etc/GMT-8", requested_urls[0])
        finally:
            self.module._make_request_with_retry = original_request

    def test_forecast_rejects_missing_precipitation_probability(self):
        data = {
            "daily": {
                "time": ["2026-07-17"],
                "weather_code": [0],
                "temperature_2m_mean": [30],
                "precipitation_probability_max": [],
            }
        }

        with self.assertRaises(ValueError):
            self.module._parse_forecast_data(data, 1)


if __name__ == "__main__":
    unittest.main()
