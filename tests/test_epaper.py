import importlib.util
import sys
import types
import unittest
from pathlib import Path


class EpaperSleepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_modules = {
            name: sys.modules.get(name)
            for name in ("machine", "framebuf", "utime")
        }

        machine = types.ModuleType("machine")
        machine.Pin = type("Pin", (), {})
        machine.SPI = type("SPI", (), {})
        machine.I2C = type("I2C", (), {})
        sys.modules["machine"] = machine
        sys.modules["framebuf"] = types.ModuleType("framebuf")
        sys.modules["utime"] = types.ModuleType("utime")

        source = Path(__file__).resolve().parents[1] / "src" / "epaper.py"
        spec = importlib.util.spec_from_file_location("epaper_sleep_test_target", source)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("epaper_sleep_test_target", None)
        for name, module in cls.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_sleep_releases_hardware_through_driver_config(self):
        epd = object.__new__(self.module.EPD_2in9)
        calls = []
        epd.config = types.SimpleNamespace(
            delay_ms=lambda value: calls.append(("delay_ms", value)),
            module_exit=lambda: calls.append(("module_exit",)),
        )
        epd.send_command = lambda value: calls.append(("command", value))
        epd.send_data = lambda value: calls.append(("data", value))

        epd.sleep()

        self.assertEqual(
            calls,
            [
                ("command", 0x10),
                ("data", 0x01),
                ("delay_ms", 2000),
                ("module_exit",),
            ],
        )


if __name__ == "__main__":
    unittest.main()
