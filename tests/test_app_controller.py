import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path


class AppControllerDateChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_modules = {
            name: sys.modules.get(name)
            for name in (
                "config_manager",
                "netutils",
                "weather",
                "display_manager",
                "display_utils",
                "image_manager",
                "wifi_manager",
                "chime",
                "discord_notifier",
                "presence_manager",
                "env_manager",
            )
        }
        cls.sync_calls = []
        cls.clear_calls = []

        config_module = types.ModuleType("config_manager")
        config_module.config_manager = types.SimpleNamespace(
            get=lambda _key, default=None: default,
            get_global=lambda _key, default=None: default,
        )
        sys.modules["config_manager"] = config_module

        netutils_module = types.ModuleType("netutils")
        netutils_module.sync_time = lambda: cls.sync_calls.append(True)
        netutils_module.get_local_time = lambda offset=0: (2026, 7, 17, 0, 0, 0, 4, 198)
        sys.modules["netutils"] = netutils_module

        weather_module = types.ModuleType("weather")
        weather_module.fetch_current_weather = lambda *_args: None
        weather_module.fetch_weather_forecast = lambda *_args, **_kwargs: []
        sys.modules["weather"] = weather_module

        display_module = types.ModuleType("display_manager")
        for name in (
            "update_page_weather",
            "update_page_time_image",
            "update_page_birthday",
            "update_page_image_preview",
        ):
            setattr(display_module, name, lambda *_args, **_kwargs: None)
        sys.modules["display_manager"] = display_module

        display_utils_module = types.ModuleType("display_utils")
        display_utils_module.release_display_workspace = lambda: None
        display_utils_module.clear_display_and_sleep = lambda: cls.clear_calls.append(True)
        sys.modules["display_utils"] = display_utils_module

        image_module = types.ModuleType("image_manager")
        image_module.image_catalog = types.SimpleNamespace()
        image_module.image_store = types.SimpleNamespace()
        sys.modules["image_manager"] = image_module

        wifi_module = types.ModuleType("wifi_manager")
        wifi_module.reset_wifi_and_reboot = lambda: None
        sys.modules["wifi_manager"] = wifi_module

        chime_module = types.ModuleType("chime")
        chime_module.Chime = lambda *_args, **_kwargs: None
        sys.modules["chime"] = chime_module

        discord_module = types.ModuleType("discord_notifier")
        discord_module.send_lan_ip = lambda *_args: False
        discord_module.send_presence_session = lambda *_args: False
        discord_module.send_presence_summary = lambda *_args: False
        sys.modules["discord_notifier"] = discord_module

        presence_module = types.ModuleType("presence_manager")
        presence_module.PresenceManager = type("PresenceManager", (), {})
        presence_module.set_presence_manager = lambda *_args: None
        sys.modules["presence_manager"] = presence_module

        env_module = types.ModuleType("env_manager")
        env_module.EnvManager = type(
            "EnvManager", (), {"__init__": lambda self, *_a, **_kw: None, "update": lambda self, *_a, **_kw: None}
        )
        env_module.set_env_manager = lambda *_args: None
        sys.modules["env_manager"] = env_module

        source = Path(__file__).resolve().parents[1] / "src" / "app_controller.py"
        spec = importlib.util.spec_from_file_location("app_controller_test_target", source)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def setUp(self):
        self.sync_calls.clear()
        self.clear_calls.clear()

    def test_new_day_resets_weather_retry_gates(self):
        state = types.SimpleNamespace(
            last_day=16,
            current_weather=(30, "Clouds"),
            current_weather_last_updated=123,
            current_weather_last_attempted=456,
            weather_forecast=[("07-16", 29, "Clouds", 20)],
            weather_forecast_last_updated=789,
            weather_forecast_last_attempted=987,
            is_first_run=False,
        )
        controller = object.__new__(self.module.AppController)
        controller.state = state

        self.assertTrue(controller._handle_date_change(17))
        self.assertEqual(state.last_day, 17)
        self.assertIsNone(state.current_weather)
        self.assertIsNone(state.weather_forecast)
        self.assertEqual(state.current_weather_last_updated, -1)
        self.assertEqual(state.current_weather_last_attempted, -1)
        self.assertEqual(state.weather_forecast_last_updated, -1)
        self.assertEqual(state.weather_forecast_last_attempted, -1)
        self.assertEqual(self.sync_calls, [True])

        self.assertFalse(controller._handle_date_change(17))
        self.assertEqual(self.sync_calls, [True])

    def test_new_day_allows_immediate_weather_requests(self):
        state = types.SimpleNamespace(
            last_day=16,
            current_weather=(30, "Clouds"),
            current_weather_last_updated=123,
            current_weather_last_attempted=456,
            weather_forecast=[("07-16", 29, "Clouds", 20)],
            weather_forecast_last_updated=789,
            weather_forecast_last_attempted=987,
            is_first_run=False,
        )
        controller = object.__new__(self.module.AppController)
        controller.state = state
        controller.api_key = "test-key"
        controller.location = "Zhunan"
        controller.time_zone_offset = 8

        original_ticks_ms = getattr(time, "ticks_ms", None)
        original_ticks_diff = getattr(time, "ticks_diff", None)
        original_current = self.module.fetch_current_weather
        original_forecast = self.module.fetch_weather_forecast
        calls = []
        try:
            time.ticks_ms = lambda: 100000
            time.ticks_diff = lambda new, old: new - old
            self.module.fetch_current_weather = lambda *_args: calls.append("current") or (30, "Clouds")
            self.module.fetch_weather_forecast = lambda *_args, **kwargs: calls.append(
                ("forecast", kwargs["days_limit"])
            ) or [("07-17", 29, "Clouds", 20)]

            controller._handle_date_change(17)

            self.assertTrue(controller._update_weather())
            self.assertEqual(calls, ["current", ("forecast", 5)])
        finally:
            self.module.fetch_current_weather = original_current
            self.module.fetch_weather_forecast = original_forecast
            if original_ticks_ms is None:
                delattr(time, "ticks_ms")
            else:
                time.ticks_ms = original_ticks_ms
            if original_ticks_diff is None:
                delattr(time, "ticks_diff")
            else:
                time.ticks_diff = original_ticks_diff

    def test_confirmed_away_transition_clears_display_once(self):
        class FakePresence:
            def __init__(self):
                self.states = iter((True, False, False, True))
                self.responses = iter((False, True, False, False))
                self.current_state = None

            def update(self, *_args):
                self.current_state = next(self.states)
                return next(self.responses)

            def flush_discord(self):
                return False

        state = types.SimpleNamespace(
            last_touch_time=-1,
            is_first_run=False,
            partial_update=True,
            last_minute=-1,
        )
        adc_values = iter((200, 60000, 200, 200))
        hardware = types.SimpleNamespace(
            get_adc_value=lambda: next(adc_values),
            get_touch_state=lambda: None,
            handle_button_long_press=lambda _callback: None,
        )
        class TestController(self.module.AppController):
            pass

        controller = object.__new__(TestController)
        controller.state = state
        controller.hw = hardware
        controller.lan_server = None
        controller.presence = FakePresence()
        controller.env = types.SimpleNamespace(update=lambda *_args, **_kwargs: None)
        controller.time_zone_offset = 8
        controller._send_startup_discord_if_ready = lambda: False
        controller._startup_discord_pending = lambda: False
        display_updates = []
        controller._handle_date_change = lambda _day: False
        controller._perform_chime = lambda _time: None
        controller._update_sensor_data = lambda: None
        controller._update_weather = lambda: False
        controller._update_display = lambda _time: display_updates.append(True)
        controller.handle_touch = lambda _touch: None

        original_consume_preview = getattr(self.module.image_store, "consume_preview", None)
        self.module.image_store.consume_preview = lambda: None
        try:
            for _ in range(4):
                controller.run_main_loop()
        finally:
            if original_consume_preview is None:
                delattr(self.module.image_store, "consume_preview")
            else:
                self.module.image_store.consume_preview = original_consume_preview

        self.assertEqual(self.clear_calls, [True])
        self.assertEqual(len(display_updates), 2)
        self.assertFalse(state.is_first_run)
        self.assertTrue(state.partial_update)


if __name__ == "__main__":
    unittest.main()
