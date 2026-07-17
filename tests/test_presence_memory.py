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

    def test_read_lines_keeps_only_recent_entries(self):
        original_event_file = self.module.EVENT_FILE
        original_daily_file = self.module.DAILY_FILE
        try:
            with tempfile.TemporaryDirectory() as directory:
                event_file = Path(directory) / "events.log"
                daily_file = Path(directory) / "daily.log"
                event_file.write_text(
                    "\n".join(["x" * 257] + [
                        "event-{}".format(index) for index in range(140)
                    ]) + "\n",
                    encoding="utf-8",
                )
                daily_file.write_text(
                    "\n".join("daily-{}".format(index) for index in range(380)) + "\n",
                    encoding="utf-8",
                )
                self.module.EVENT_FILE = str(event_file)
                self.module.DAILY_FILE = str(daily_file)

                events = self.module._read_lines(self.module.EVENT_FILE)
                daily = self.module._read_lines(self.module.DAILY_FILE)

                self.assertEqual(len(events), self.module.MAX_EVENT_LINES_IN_MEMORY)
                self.assertNotIn("x" * 257, events)
                self.assertEqual(events[0], "event-12")
                self.assertEqual(events[-1], "event-139")
                self.assertEqual(len(daily), self.module.MAX_DAILY_LINES_IN_MEMORY)
                self.assertEqual(daily[0], "daily-14")
                self.assertEqual(daily[-1], "daily-379")
        finally:
            self.module.EVENT_FILE = original_event_file
            self.module.DAILY_FILE = original_daily_file

    def test_away_and_return_states_wait_for_independent_timeouts(self):
        original_paths = {
            name: getattr(self.module, name)
            for name in ("EVENT_FILE", "DAILY_FILE", "PENDING_FILE", "PENDING_SESSION_FILE")
        }
        original_mktime = self.module.time.mktime

        def local_time(seconds):
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return (2026, 7, 15, hours, minutes, seconds, 2, 0)

        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.module.EVENT_FILE = str(root / "events.log")
                self.module.DAILY_FILE = str(root / "daily.log")
                self.module.PENDING_FILE = str(root / "summary.log")
                self.module.PENDING_SESSION_FILE = str(root / "session.log")
                self.module.time.mktime = lambda value: value[3] * 3600 + value[4] * 60 + value[5]

                manager = self.module.PresenceManager()
                manager.update(100, 200, local_time(0), 180, 10)
                manager.update(300, 200, local_time(120), 180, 10)
                self.assertEqual(manager.get_status()["state"], 1)
                manager.update(100, 200, local_time(150), 180, 10)
                self.assertEqual(manager.get_status()["state"], 1)

                manager.update(300, 200, local_time(180), 180, 10)
                manager.update(300, 200, local_time(360), 180, 10)
                self.assertEqual(manager.get_status()["state"], 0)
                manager.update(100, 200, local_time(361), 180)
                self.assertEqual(manager.get_status()["state"], 0)
                manager.update(100, 200, local_time(370), 180)
                self.assertEqual(manager.get_status()["state"], 0)
                manager.update(100, 200, local_time(371), 180)
                self.assertEqual(manager.get_status()["state"], 1)

                self.assertEqual(
                    [line.split(",")[2] for line in Path(self.module.EVENT_FILE).read_text().splitlines()],
                    ["1", "0", "1"],
                )
        finally:
            self.module.time.mktime = original_mktime
            for name, value in original_paths.items():
                setattr(self.module, name, value)

    def test_update_reports_only_confirmed_away_transition(self):
        original_paths = {
            name: getattr(self.module, name)
            for name in ("EVENT_FILE", "DAILY_FILE", "PENDING_FILE", "PENDING_SESSION_FILE")
        }
        original_mktime = self.module.time.mktime

        def local_time(seconds):
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return (2026, 7, 15, hours, minutes, seconds, 2, 0)

        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.module.EVENT_FILE = str(root / "events.log")
                self.module.DAILY_FILE = str(root / "daily.log")
                self.module.PENDING_FILE = str(root / "summary.log")
                self.module.PENDING_SESSION_FILE = str(root / "session.log")
                self.module.time.mktime = lambda value: value[3] * 3600 + value[4] * 60 + value[5]

                manager = self.module.PresenceManager()
                self.assertFalse(manager.update(100, 200, local_time(0), 3, 10))
                self.assertFalse(manager.update(300, 200, local_time(1), 3, 10))
                self.assertTrue(manager.update(300, 200, local_time(4), 3, 10))
                self.assertFalse(manager.update(300, 200, local_time(5), 3, 10))
        finally:
            self.module.time.mktime = original_mktime
            for name, value in original_paths.items():
                setattr(self.module, name, value)

    def test_restored_open_session_starts_away_timeout_from_first_sample(self):
        original_paths = {
            name: getattr(self.module, name)
            for name in ("EVENT_FILE", "DAILY_FILE", "PENDING_FILE", "PENDING_SESSION_FILE")
        }
        original_mktime = self.module.time.mktime

        def local_time(seconds):
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return (2026, 7, 15, hours, minutes, seconds, 2, 0)

        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.module.EVENT_FILE = str(root / "events.log")
                self.module.DAILY_FILE = str(root / "daily.log")
                self.module.PENDING_FILE = str(root / "summary.log")
                self.module.PENDING_SESSION_FILE = str(root / "session.log")
                Path(self.module.EVENT_FILE).write_text("20260715,000000,1,100\n", encoding="utf-8")
                self.module.time.mktime = lambda value: value[3] * 3600 + value[4] * 60 + value[5]

                manager = self.module.PresenceManager()
                manager.update(300, 200, local_time(600), 180, 10)
                self.assertEqual(manager.get_status()["state"], 1)
                manager.update(300, 200, local_time(780), 180, 10)
                self.assertEqual(manager.get_status()["state"], 0)
        finally:
            self.module.time.mktime = original_mktime
            for name, value in original_paths.items():
                setattr(self.module, name, value)

    def test_restored_away_state_waits_for_return_timeout(self):
        original_paths = {
            name: getattr(self.module, name)
            for name in ("EVENT_FILE", "DAILY_FILE", "PENDING_FILE", "PENDING_SESSION_FILE")
        }
        original_mktime = self.module.time.mktime

        def local_time(seconds):
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return (2026, 7, 15, hours, minutes, seconds, 2, 0)

        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.module.EVENT_FILE = str(root / "events.log")
                self.module.DAILY_FILE = str(root / "daily.log")
                self.module.PENDING_FILE = str(root / "summary.log")
                self.module.PENDING_SESSION_FILE = str(root / "session.log")
                Path(self.module.EVENT_FILE).write_text("20260715,000000,0,300\n", encoding="utf-8")
                self.module.time.mktime = lambda value: value[3] * 3600 + value[4] * 60 + value[5]

                manager = self.module.PresenceManager()
                manager.update(100, 200, local_time(600), 180, 10)
                self.assertEqual(manager.get_status()["state"], 0)
                manager.update(100, 200, local_time(609), 180, 10)
                self.assertEqual(manager.get_status()["state"], 0)
                manager.update(100, 200, local_time(610), 180, 10)
                self.assertEqual(manager.get_status()["state"], 1)
        finally:
            self.module.time.mktime = original_mktime
            for name, value in original_paths.items():
                setattr(self.module, name, value)


if __name__ == "__main__":
    unittest.main()
