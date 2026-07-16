import importlib.util
import sys
import tempfile
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

    def test_startup_flush_drains_pending_session_and_summary_files(self):
        original_pending = self.module.PENDING_FILE
        original_session_pending = self.module.PENDING_SESSION_FILE
        try:
            with tempfile.TemporaryDirectory() as directory:
                self.module.PENDING_FILE = str(Path(directory) / "summary.log")
                self.module.PENDING_SESSION_FILE = str(Path(directory) / "session.log")
                Path(self.module.PENDING_FILE).write_text("20260715,1,1,1,1\n", encoding="utf-8")
                Path(self.module.PENDING_SESSION_FILE).write_text(
                    "20260715,090000,20260715,090100,60\n", encoding="utf-8"
                )
                sent = []
                manager = self.module.PresenceManager(
                    discord_sender=lambda summary: sent.append(("summary", summary)) or True,
                    session_sender=lambda *values: sent.append(("session", values)) or True,
                )

                self.assertEqual(manager.flush_startup_discord(), 2)
                self.assertEqual([kind for kind, _value in sent], ["session", "summary"])
                self.assertEqual(Path(self.module.PENDING_FILE).read_text(encoding="utf-8"), "")
                self.assertEqual(Path(self.module.PENDING_SESSION_FILE).read_text(encoding="utf-8"), "")
        finally:
            self.module.PENDING_FILE = original_pending
            self.module.PENDING_SESSION_FILE = original_session_pending

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
