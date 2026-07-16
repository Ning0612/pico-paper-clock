import importlib.util
import io
import json
import sys
import time
import types
import unittest
from pathlib import Path


class WeatherStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_modules = {
            name: sys.modules.get(name)
            for name in ("urequests", "network", "ujson", "weather")
        }
        sys.modules["urequests"] = types.ModuleType("urequests")
        sys.modules["network"] = types.ModuleType("network")
        sys.modules["network"].STA_IF = 0
        sys.modules["network"].WLAN = lambda _interface: types.SimpleNamespace(isconnected=lambda: True)
        sys.modules["ujson"] = json

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

    def test_forecast_parser_uses_stream_entries_without_full_json_document(self):
        payload = json.dumps({
            "list": [
                {"dt": 1, "main": {"temp": 20}, "weather": [{"main": "Clear"}]},
                {"dt": 2, "main": {"temp": 21}, "weather": [{"main": "Clouds"}]},
            ]
        }).encode()
        class CountingStream(io.BytesIO):
            def __init__(self, value):
                super().__init__(value)
                self.readinto_calls = 0

            def readinto(self, buffer):
                self.readinto_calls += 1
                return super().readinto(buffer)

        raw = CountingStream(payload)
        response = types.SimpleNamespace(raw=raw)

        entries = list(self.module._iter_forecast_entries(response))

        self.assertEqual(len(entries), 2)
        self.assertGreater(raw.readinto_calls, 0)
        self.assertEqual(json.loads(entries[0].decode())["main"]["temp"], 20)
        self.assertEqual(json.loads(entries[1].decode())["weather"][0]["main"], "Clouds")

    def test_forecast_stream_falls_back_to_read_when_readinto_is_unavailable(self):
        class ReadOnlyStream:
            def __init__(self, value):
                self.value = value

            def read(self, size):
                chunk, self.value = self.value[:size], self.value[size:]
                return chunk

        values = list(self.module._iter_raw_bytes(ReadOnlyStream(b"abc")))

        self.assertEqual(values, [97, 98, 99])

    def test_forecast_stream_rejects_nonblocking_or_error_read_result(self):
        class BadStream:
            def __init__(self, result):
                self.result = result

            def readinto(self, _buffer):
                return self.result

        for result in (None, -5):
            with self.subTest(result=result):
                with self.assertRaises(OSError):
                    list(self.module._iter_raw_bytes(BadStream(result)))

    def test_forecast_aggregation_supports_today_plus_four_future_days(self):
        base = int(time.mktime((2026, 7, 17, 0, 0, 0, 0, 0, -1)))
        payload = json.dumps({
            "list": [
                {
                    "dt": base + index * 86400,
                    "main": {"temp": 20 + index},
                    "weather": [{"main": "Clear"}],
                }
                for index in range(5)
            ]
        }).encode()
        response = types.SimpleNamespace(raw=io.BytesIO(payload))

        result = self.module._aggregate_forecast_stream(response, 5, 0)

        self.assertEqual(len(result), 5)
        self.assertEqual(
            [item[0] for item in result],
            ["07-17", "07-18", "07-19", "07-20", "07-21"],
        )

    def test_forecast_retries_when_response_has_too_few_days(self):
        class Response:
            status_code = 200

            def close(self):
                pass

        original_request = self.module._make_request_with_retry
        original_aggregate = self.module._aggregate_forecast_stream
        requested_urls = []
        aggregate_calls = []
        try:
            self.module._make_request_with_retry = lambda url: requested_urls.append(url) or Response()

            def aggregate(_response, _days_limit, _timezone_offset):
                aggregate_calls.append(True)
                return list(range(4 if len(aggregate_calls) == 1 else 5))

            self.module._aggregate_forecast_stream = aggregate

            result = self.module.fetch_weather_forecast("key", "Zhunan", days_limit=5, timezone_offset=8)

            self.assertEqual(result, [0, 1, 2, 3, 4])
            self.assertEqual(len(aggregate_calls), 2)
            self.assertIn("cnt=40", requested_urls[0])
            self.assertIn("cnt=32", requested_urls[1])
        finally:
            self.module._make_request_with_retry = original_request
            self.module._aggregate_forecast_stream = original_aggregate


if __name__ == "__main__":
    unittest.main()
