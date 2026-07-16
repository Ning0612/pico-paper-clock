import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path


class PresenceMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_modules = {
            name: sys.modules.get(name) for name in ("config_manager", "presence_manager")
        }
        cls.original_ticks = {
            name: getattr(time, name, None)
            for name in ("ticks_ms", "ticks_add", "ticks_diff")
        }
        time.ticks_ms = lambda: 1000
        time.ticks_add = lambda value, delta: value + delta
        time.ticks_diff = lambda new, old: new - old

        config_module = types.ModuleType("config_manager")
        config_module.config_manager = types.SimpleNamespace(
            get=lambda _key, default=None: default
        )
        sys.modules["config_manager"] = config_module

        source = Path(__file__).resolve().parents[1] / "src" / "presence_manager.py"
        spec = importlib.util.spec_from_file_location("presence_manager", source)
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules["presence_manager"] = cls.module
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

    def test_enomem_disables_pending_presence_retries(self):
        manager = self.module.PresenceManager(
            discord_sender=lambda _summary: None,
            session_sender=lambda *_args: None,
        )
        manager.pending_summary = "20260713,1,1,1,1"

        self.assertFalse(manager.flush_discord())
        self.assertTrue(manager.discord_disabled)
        self.assertFalse(manager.flush_discord())

    def test_daily_retention_covers_year_heatmap_without_extending_events(self):
        manager = self.module.PresenceManager(
            discord_sender=lambda _summary: None,
            session_sender=lambda *_args: None,
        )
        calls = []
        original_trim = self.module._trim_by_date
        original_mktime = self.module.time.mktime
        self.module._trim_by_date = lambda path, date: calls.append((path, date))
        self.module.time.mktime = lambda value: original_mktime(tuple(value) + (0,))
        try:
            manager._trim_retention("20260714")
        finally:
            self.module._trim_by_date = original_trim
            self.module.time.mktime = original_mktime

        self.assertEqual([path for path, _date in calls], [
            self.module.EVENT_FILE,
            self.module.DAILY_FILE,
        ])
        self.assertLess(calls[1][1], calls[0][1])

    def test_status_exposes_device_current_date_for_web_clients(self):
        manager = self.module.PresenceManager(
            discord_sender=lambda _summary: None,
            session_sender=lambda *_args: None,
        )
        manager.current_date = "20260715"

        self.assertEqual(manager.get_status()["current_date"], "20260715")


if __name__ == "__main__":
    unittest.main()
