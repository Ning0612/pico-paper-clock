import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path


class FakeSensor:
    def __init__(self):
        self.measure_calls = 0
        self.temperature_value = 23.4
        self.humidity_value = 51.2
        self.error = None

    def measure(self):
        self.measure_calls += 1
        if self.error:
            raise self.error

    def temperature(self):
        return self.temperature_value

    def humidity(self):
        return self.humidity_value


class HardwareManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_modules = {
            name: sys.modules.get(name)
            for name in ("dht", "machine", "epaper", "hardware_manager")
        }
        cls.original_ticks = {
            name: getattr(time, name, None)
            for name in ("ticks_ms", "ticks_add", "ticks_diff")
        }
        cls.now = 1000
        time.ticks_ms = lambda: cls.now
        time.ticks_add = lambda value, delta: value + delta
        time.ticks_diff = lambda new, old: new - old

        cls.sensor = FakeSensor()
        dht_module = types.ModuleType("dht")
        dht_module.DHT22 = lambda _pin: cls.sensor
        sys.modules["dht"] = dht_module

        class Pin:
            IN = 0
            PULL_UP = 1

            def __init__(self, value, *_args):
                self.value_number = value

            def value(self):
                return 1

        machine_module = types.ModuleType("machine")
        machine_module.Pin = Pin
        machine_module.ADC = lambda _pin: types.SimpleNamespace(read_u16=lambda: 0)
        sys.modules["machine"] = machine_module

        epaper_module = types.ModuleType("epaper")
        epaper_module.ICNT86 = type("ICNT86", (), {"ICNT_Init": lambda _self: None})
        epaper_module.ICNT_Development = type("ICNT_Development", (), {})
        epaper_module.get_touch_state = lambda *_args: None
        sys.modules["epaper"] = epaper_module

        source = Path(__file__).resolve().parents[1] / "src" / "hardware_manager.py"
        spec = importlib.util.spec_from_file_location("hardware_manager", source)
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules["hardware_manager"] = cls.module
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name, value in cls.original_ticks.items():
            if value is None:
                delattr(time, name)
            else:
                setattr(time, name, value)

    def setUp(self):
        self.now = 1000
        type(self).now = self.now
        type(self).sensor.measure_calls = 0
        type(self).sensor.error = None
        self.hardware = self.module.HardwareManager()

    def test_successful_read_is_cached_until_minimum_interval(self):
        self.assertEqual(self.hardware.get_temperature_humidity(), (23.4, 51.2))
        type(self).now += 2499
        self.assertEqual(self.hardware.get_temperature_humidity(), (23.4, 51.2))
        self.assertEqual(type(self).sensor.measure_calls, 1)
        type(self).now += 1
        self.assertEqual(self.hardware.get_temperature_humidity(), (23.4, 51.2))
        self.assertEqual(type(self).sensor.measure_calls, 2)

    def test_failed_read_is_backed_off_and_does_not_discard_cache(self):
        self.assertEqual(self.hardware.get_temperature_humidity(), (23.4, 51.2))
        type(self).now += 2500
        type(self).sensor.error = OSError(110)
        self.assertEqual(self.hardware.get_temperature_humidity(), (23.4, 51.2))
        calls_after_failure = type(self).sensor.measure_calls
        type(self).now += 9999
        self.assertEqual(self.hardware.get_temperature_humidity(), (23.4, 51.2))
        self.assertEqual(type(self).sensor.measure_calls, calls_after_failure)
        type(self).sensor.error = None
        type(self).now += 1
        self.assertEqual(self.hardware.get_temperature_humidity(), (23.4, 51.2))
        self.assertEqual(type(self).sensor.measure_calls, calls_after_failure + 1)


if __name__ == "__main__":
    unittest.main()
