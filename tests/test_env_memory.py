import importlib.util
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path


class FakeHardware:
    def __init__(self, readings=None):
        self._readings = list(readings) if readings is not None else []

    def get_temperature_humidity(self):
        if not self._readings:
            return None
        return self._readings.pop(0)


class EnvMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_modules = {
            name: sys.modules.get(name)
            for name in ("config_manager", "presence_manager", "env_manager")
        }

        config_module = types.ModuleType("config_manager")
        config_module.config_manager = types.SimpleNamespace(
            get=lambda _key, default=None: default
        )
        sys.modules["config_manager"] = config_module

        repo_src = Path(__file__).resolve().parents[1] / "src"

        presence_spec = importlib.util.spec_from_file_location(
            "presence_manager", repo_src / "presence_manager.py"
        )
        presence_module = importlib.util.module_from_spec(presence_spec)
        sys.modules["presence_manager"] = presence_module
        presence_spec.loader.exec_module(presence_module)

        env_spec = importlib.util.spec_from_file_location(
            "env_manager", repo_src / "env_manager.py"
        )
        cls.module = importlib.util.module_from_spec(env_spec)
        sys.modules["env_manager"] = cls.module
        env_spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def _local_time(self, seconds, day=15):
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return (2026, 7, day, hours, minutes, seconds, 2, 0)

    def _patch_paths(self):
        original_paths = {
            name: getattr(self.module, name) for name in ("EVENT_FILE", "DAILY_FILE")
        }
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        self.module.EVENT_FILE = str(root / "events.log")
        self.module.DAILY_FILE = str(root / "daily.log")
        return directory, original_paths

    def _restore_paths(self, original_paths):
        for name, value in original_paths.items():
            setattr(self.module, name, value)

    def _patch_intraday_mktime(self):
        original_mktime = self.module.time.mktime
        self.module.time.mktime = lambda value: value[3] * 3600 + value[4] * 60 + value[5]
        return original_mktime

    def test_retention_trims_samples_and_daily_by_different_windows(self):
        directory, original_paths = self._patch_paths()
        original_mktime = self.module.time.mktime
        calls = []
        original_trim = self.module._trim_by_date
        self.module._trim_by_date = lambda path, date: calls.append((path, date))
        self.module.time.mktime = lambda value: original_mktime(tuple(value) + (0,))
        try:
            manager = self.module.EnvManager()
            manager.current_date = "20260714"
            manager._trim_retention("20260714")

            self.assertEqual([path for path, _date in calls], [
                self.module.EVENT_FILE,
                self.module.DAILY_FILE,
            ])
            self.assertGreater(calls[0][1], calls[1][1])
        finally:
            self.module._trim_by_date = original_trim
            self.module.time.mktime = original_mktime
            self._restore_paths(original_paths)
            directory.cleanup()

    def test_rollover_appends_summary_line_and_resets_today_stats(self):
        directory, original_paths = self._patch_paths()
        original_mktime = self.module.time.mktime
        self.module.time.mktime = lambda value: original_mktime(tuple(value) + (0,))
        try:
            manager = self.module.EnvManager()
            manager.current_date = "20260714"
            manager.today_t_min, manager.today_t_max, manager.today_t_sum = 20.0, 28.0, 92.0
            manager.today_h_min, manager.today_h_max, manager.today_h_sum = 40.0, 60.0, 200.0
            manager.today_count = 4

            manager._rollover_day("20260715")

            lines = Path(self.module.DAILY_FILE).read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines, ["20260714,20.0,28.0,23.0,40.0,60.0,50.0,4"])
            self.assertEqual(manager.current_date, "20260715")
            self.assertIsNone(manager.today_t_min)
            self.assertEqual(manager.today_count, 0)
        finally:
            self.module.time.mktime = original_mktime
            self._restore_paths(original_paths)
            directory.cleanup()

    def test_restore_on_boot_reconstructs_today_stats_and_last_sample_epoch(self):
        directory, original_paths = self._patch_paths()
        original_mktime = self._patch_intraday_mktime()
        try:
            Path(self.module.EVENT_FILE).write_text(
                "20260715,0900,22.0,50.0\n20260715,0915,24.0,55.0\n",
                encoding="utf-8",
            )
            manager = self.module.EnvManager()
            hw = FakeHardware()

            manager.update(self._local_time(9 * 3600 + 20 * 60), hw)

            status = manager.get_status()
            self.assertEqual(status["t_min"], 22.0)
            self.assertEqual(status["t_max"], 24.0)
            self.assertAlmostEqual(status["t_avg"], 23.0)
            self.assertEqual(status["count"], 2)
            self.assertEqual(status["current_date"], "20260715")
        finally:
            self.module.time.mktime = original_mktime
            self._restore_paths(original_paths)
            directory.cleanup()

    def test_read_env_lines_keeps_only_recent_entries_and_drops_oversized_lines(self):
        directory, original_paths = self._patch_paths()
        try:
            Path(self.module.EVENT_FILE).write_text(
                "\n".join(["x" * 49] + [
                    "sample-{}".format(index) for index in range(710)
                ]) + "\n",
                encoding="utf-8",
            )

            lines = self.module._read_env_lines(self.module.EVENT_FILE)

            self.assertEqual(len(lines), self.module.MAX_SAMPLE_LINES_IN_MEMORY)
            self.assertNotIn("x" * 49, lines)
            self.assertEqual(lines[-1], "sample-709")
        finally:
            self._restore_paths(original_paths)
            directory.cleanup()

    def test_sample_interval_throttle_writes_one_line_per_interval(self):
        directory, original_paths = self._patch_paths()
        original_mktime = self._patch_intraday_mktime()
        try:
            manager = self.module.EnvManager(sample_interval_min=15)
            hw = FakeHardware(readings=[(21.0, 50.0), (21.5, 51.0), (22.0, 52.0)])

            manager.update(self._local_time(0), hw)
            manager.update(self._local_time(5 * 60), hw)
            manager.update(self._local_time(14 * 60), hw)

            lines = Path(self.module.EVENT_FILE).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)

            manager.update(self._local_time(15 * 60 + 1), hw)
            lines = Path(self.module.EVENT_FILE).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
        finally:
            self.module.time.mktime = original_mktime
            self._restore_paths(original_paths)
            directory.cleanup()

    def test_clock_guard_skips_writes_before_ntp_sync(self):
        directory, original_paths = self._patch_paths()
        try:
            manager = self.module.EnvManager()
            hw = FakeHardware(readings=[(21.0, 50.0)])

            manager.update((1970, 1, 1, 0, 0, 0, 3, 1), hw)

            self.assertIsNone(manager.current_date)
            self.assertFalse(Path(self.module.EVENT_FILE).exists())
        finally:
            self._restore_paths(original_paths)
            directory.cleanup()

    def test_sensor_none_reading_does_not_write_or_crash(self):
        directory, original_paths = self._patch_paths()
        original_mktime = self._patch_intraday_mktime()
        try:
            manager = self.module.EnvManager()
            hw = FakeHardware(readings=[])

            manager.update(self._local_time(0), hw)

            self.assertFalse(Path(self.module.EVENT_FILE).exists())
            self.assertIsNone(manager.last_temp)
        finally:
            self.module.time.mktime = original_mktime
            self._restore_paths(original_paths)
            directory.cleanup()

    def test_get_status_shape_reports_current_and_today_aggregates(self):
        directory, original_paths = self._patch_paths()
        original_mktime = self._patch_intraday_mktime()
        try:
            manager = self.module.EnvManager()
            hw = FakeHardware(readings=[(20.0, 45.0), (24.0, 55.0)])

            manager.update(self._local_time(0), hw)
            manager.update(self._local_time(20 * 60), hw)

            status = manager.get_status()
            self.assertEqual(status["temp"], 24.0)
            self.assertEqual(status["hum"], 55.0)
            self.assertEqual(status["t_min"], 20.0)
            self.assertEqual(status["t_max"], 24.0)
            self.assertAlmostEqual(status["t_avg"], 22.0)
            self.assertEqual(status["count"], 2)
            self.assertEqual(status["now_epoch"], 20 * 60)
        finally:
            self.module.time.mktime = original_mktime
            self._restore_paths(original_paths)
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
