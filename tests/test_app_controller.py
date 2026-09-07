import ast
import importlib.util
import re
import sys
import symtable
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
        weather_module.fetch_weather_bundle = lambda *_args, **_kwargs: None
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

    def test_new_day_resets_weather_retry_gates_but_retains_weather(self):
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
        self.assertEqual(state.current_weather, (30, "Clouds"))
        self.assertEqual(state.weather_forecast, [("07-16", 29, "Clouds", 20)])
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
        controller.weather_latitude = 24.6855
        controller.weather_longitude = 120.8789
        controller.time_zone_offset = 8

        original_ticks_ms = getattr(time, "ticks_ms", None)
        original_ticks_diff = getattr(time, "ticks_diff", None)
        original_bundle = self.module.fetch_weather_bundle
        calls = []
        try:
            time.ticks_ms = lambda: 100000
            time.ticks_diff = lambda new, old: new - old
            self.module.fetch_weather_bundle = lambda *_args, **kwargs: calls.append(
                ("bundle", kwargs["days_limit"])
            ) or ((30, "Clouds"), [("07-17", 29, "Clouds", 20)])

            controller._handle_date_change(17)

            self.assertTrue(controller._update_weather())
            self.assertEqual(calls, [("bundle", 5)])
        finally:
            self.module.fetch_weather_bundle = original_bundle
            if original_ticks_ms is None:
                delattr(time, "ticks_ms")
            else:
                time.ticks_ms = original_ticks_ms
            if original_ticks_diff is None:
                delattr(time, "ticks_diff")
            else:
                time.ticks_diff = original_ticks_diff

    def test_weather_failure_retains_last_known_good_data(self):
        state = types.SimpleNamespace(
            last_day=17,
            current_weather=(30, "Clear"),
            current_weather_last_updated=1,
            current_weather_last_attempted=-1,
            weather_forecast=[("07-17", 29, "Clouds", 20)],
            weather_forecast_last_updated=1,
            weather_forecast_last_attempted=-1,
            is_first_run=False,
        )
        controller = object.__new__(self.module.AppController)
        controller.state = state
        controller.weather_latitude = 24.6855
        controller.weather_longitude = 120.8789
        controller.time_zone_offset = 8

        original_bundle = self.module.fetch_weather_bundle
        original_ticks_ms = getattr(time, "ticks_ms", None)
        original_ticks_diff = getattr(time, "ticks_diff", None)
        try:
            time.ticks_ms = lambda: 2000000
            time.ticks_diff = lambda new, old: new - old
            self.module.fetch_weather_bundle = lambda *_args, **_kwargs: None

            self.assertTrue(controller._update_weather())
            self.assertEqual(state.current_weather, (30, "Clear"))
            self.assertEqual(state.weather_forecast, [("07-17", 29, "Clouds", 20)])
        finally:
            self.module.fetch_weather_bundle = original_bundle
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
            display_asleep=False,
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
        controller.boot_ms = 0
        # Already latched, so this test does not need the ticks_* shims.
        controller.min_uptime_reached = True
        controller.auto_reset_blocked = True
        controller.display_sleep_retry_ms = None
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

    def _away_controller(self, state, previews=()):
        """A controller whose presence never leaves the away state."""
        class FakePresence:
            current_state = False

            def update(self, *_args):
                return False

            def flush_discord(self):
                return False

        hardware = types.SimpleNamespace(
            get_adc_value=lambda: 60000,
            get_touch_state=lambda: None,
            handle_button_long_press=lambda _callback: None,
        )
        # __slots__ blocks per-instance method overrides; a subclass restores __dict__.
        class TestController(self.module.AppController):
            pass

        controller = object.__new__(TestController)
        controller.state = state
        controller.hw = hardware
        controller.lan_server = None
        controller.presence = FakePresence()
        controller.env = types.SimpleNamespace(update=lambda *_args, **_kwargs: None)
        controller.time_zone_offset = 8
        controller.boot_ms = 0
        controller.min_uptime_reached = True
        controller.auto_reset_blocked = True
        controller.display_sleep_retry_ms = None
        controller._send_startup_discord_if_ready = lambda: False
        controller._startup_discord_pending = lambda: False
        controller._update_display = lambda _time: self.fail("away must not draw a page")

        queued = list(previews)
        original_consume_preview = getattr(self.module.image_store, "consume_preview", None)
        self.module.image_store.consume_preview = lambda: queued.pop(0) if queued else None

        def restore():
            if original_consume_preview is None:
                delattr(self.module.image_store, "consume_preview")
            else:
                self.module.image_store.consume_preview = original_consume_preview

        self.addCleanup(restore)
        return controller

    def test_starting_up_already_away_clears_and_sleeps_the_panel_once(self):
        """A reboot in an unlit room has no away *transition* to react to.

        main.py paints the loading page before the controller exists, so without
        an idempotent away branch that page stays on a never-slept panel until
        the light comes back.
        """
        state = types.SimpleNamespace(
            last_touch_time=-1,
            is_first_run=False,
            partial_update=True,
            last_minute=-1,
            display_asleep=False,
        )
        controller = self._away_controller(state)

        for _ in range(3):
            controller.run_main_loop()

        self.assertEqual(self.clear_calls, [True])
        self.assertTrue(state.display_asleep)
        self.assertTrue(state.is_first_run)
        self.assertFalse(state.partial_update)

    def test_previews_arriving_while_away_never_bypass_the_away_branch(self):
        """The preview early return must not become a way to skip convergence.

        A client uploading with preview=true once per loop would otherwise keep
        the panel awake and starve presence, env sampling and the stall check.
        """
        previews = tuple(("/image/custom/{}.bin".format(i), 128, 128) for i in range(3))
        state = types.SimpleNamespace(
            last_touch_time=-1,
            is_first_run=False,
            partial_update=True,
            last_minute=-1,
            display_asleep=False,
        )
        controller = self._away_controller(state, previews=(None,) + previews)
        drawn = []
        original_preview_draw = self.module.update_page_image_preview
        self.addCleanup(
            setattr, self.module, "update_page_image_preview", original_preview_draw
        )
        self.module.update_page_image_preview = lambda *_args: drawn.append(True)

        # Loop 1 puts the panel to sleep; loops 2-4 each deliver a fresh preview.
        for _ in range(4):
            controller.run_main_loop()

        self.assertEqual(self.clear_calls, [True])
        self.assertEqual(drawn, [], "a sleeping panel must not be woken by a preview")
        self.assertTrue(state.display_asleep)

    def test_previews_while_present_do_not_starve_the_housekeeping(self):
        """A preview replaces one page render, never the rest of the loop.

        The old early return let a client posting preview=true once per loop
        stop presence updates (so the leave debounce never advanced), env
        sampling and the Discord stall check for as long as it kept posting.
        """
        class BusyPresence:
            current_state = True

            def __init__(self):
                self.updates = 0

            def update(self, *_args):
                self.updates += 1
                return False

            def flush_discord(self):
                return False

        state = types.SimpleNamespace(
            last_touch_time=-1,
            is_first_run=False,
            partial_update=True,
            last_minute=-1,
            display_asleep=False,
        )
        previews = [("/image/custom/{}.bin".format(i), 128, 128) for i in range(3)]
        # _update_display is wired to fail: a preview must take the render slot.
        controller = self._away_controller(state, previews=previews)
        controller.presence = BusyPresence()
        env_samples = []
        controller.env = types.SimpleNamespace(
            update=lambda *_a, **_kw: env_samples.append(True)
        )
        stall_checks = []
        controller._check_discord_stall = lambda: stall_checks.append(True)
        drawn = []
        original_preview_draw = self.module.update_page_image_preview
        self.addCleanup(
            setattr, self.module, "update_page_image_preview", original_preview_draw
        )
        self.module.update_page_image_preview = lambda *_args: drawn.append(True)

        for _ in range(3):
            controller.run_main_loop()

        self.assertEqual(len(drawn), 3)
        self.assertEqual(controller.presence.updates, 3, "presence must keep advancing")
        self.assertEqual(len(env_samples), 3, "env sampling must keep running")
        self.assertEqual(len(stall_checks), 3, "the stall check must keep running")
        self.assertEqual(self.clear_calls, [])
        self.assertEqual(
            state.last_minute, -1, "a preview must not consume the render slot's state"
        )

    def test_a_touch_landing_on_a_preview_pass_is_not_swallowed(self):
        """get_touch_state() already took the event, so this pass must use it.

        The driver does not replay it on the following pass, so leaving the
        touch to the render branch loses one image advance whenever a preview
        happens to land on the same iteration.
        """
        class BusyPresence:
            current_state = True

            def update(self, *_args):
                return False

            def flush_discord(self):
                return False

        state = types.SimpleNamespace(
            last_touch_time=-1,
            is_first_run=False,
            partial_update=True,
            last_minute=-1,
            display_asleep=False,
        )
        touch = ("Touch", (200, 40))
        controller = self._away_controller(
            state, previews=[("/image/custom/a.bin", 128, 128)]
        )
        controller.presence = BusyPresence()
        controller.hw = types.SimpleNamespace(
            get_adc_value=lambda: 200,
            get_touch_state=lambda: touch,
            handle_button_long_press=lambda _callback: None,
        )
        touches = []
        controller.handle_touch = lambda handled: touches.append(handled)
        original_preview_draw = self.module.update_page_image_preview
        self.addCleanup(
            setattr, self.module, "update_page_image_preview", original_preview_draw
        )
        self.module.update_page_image_preview = lambda *_args: None

        controller.run_main_loop()

        self.assertEqual(touches, [touch])

    def test_unknown_presence_state_is_treated_as_away(self):
        """current_state is None before the first update; fail closed, not awake."""
        class NoStatePresence:
            current_state = None

            def update(self, *_args):
                return False

            def flush_discord(self):
                return False

        state = types.SimpleNamespace(
            last_touch_time=-1,
            is_first_run=False,
            partial_update=True,
            last_minute=-1,
            display_asleep=False,
        )
        controller = self._away_controller(state)
        controller.presence = NoStatePresence()

        controller.run_main_loop()

        self.assertEqual(self.clear_calls, [True])
        self.assertTrue(state.display_asleep)


    def test_a_failing_panel_does_not_take_the_stall_check_down_with_it(self):
        """main.py drives the loop bare, so an exception here ends the program.

        The away branch is the one path every dark-room reboot takes, and the
        stall check that recovers a wedged Discord queue runs after it.
        """
        state = types.SimpleNamespace(
            last_touch_time=-1,
            is_first_run=False,
            partial_update=True,
            last_minute=-1,
            display_asleep=False,
        )
        controller = self._away_controller(state)
        original_clear = self.module.clear_display_and_sleep
        self.addCleanup(setattr, self.module, "clear_display_and_sleep", original_clear)
        clock = self._patch_ticks()

        attempts = []

        def failing_clear():
            attempts.append(True)
            raise OSError(12)

        self.module.clear_display_and_sleep = failing_clear
        stall_checks = []
        controller._check_discord_stall = lambda: stall_checks.append(True)

        for _ in range(2):
            controller.run_main_loop()

        self.assertEqual(len(stall_checks), 2, "the stall check must still run")
        self.assertFalse(state.display_asleep, "a failed sleep must stay retryable")
        self.assertEqual(
            len(attempts), 1, "a clear plus panel init is too costly to retry every pass"
        )

        clock[0] += self.module.DISPLAY_SLEEP_RETRY_MS
        controller.run_main_loop()

        self.assertEqual(len(attempts), 2, "the backoff must expire so the panel can recover")
        self.assertEqual(len(stall_checks), 3)

    def test_returning_to_the_desk_drops_a_stale_sleep_backoff(self):
        """A deadline from an earlier away period can outlive ticks_diff()'s range
        (~6.2 days), where it would read as 'not due' and leave the panel awake."""
        state = types.SimpleNamespace(
            last_touch_time=-1,
            is_first_run=False,
            partial_update=True,
            last_minute=-1,
            display_asleep=True,
        )
        controller = self._away_controller(state)
        controller.presence = types.SimpleNamespace(
            current_state=True,
            update=lambda *_args: False,
            flush_discord=lambda: False,
        )
        controller._update_display = lambda _t: None
        controller._perform_chime = lambda _t: None
        controller._update_sensor_data = lambda: None
        controller._update_weather = lambda: False
        controller._handle_date_change = lambda _day: False
        controller._check_discord_stall = lambda: None
        controller.display_sleep_retry_ms = 12345

        controller.run_main_loop()

        self.assertIsNone(controller.display_sleep_retry_ms)

    def test_a_sleep_backoff_never_outlives_the_away_period_that_set_it(self):
        """away -> present -> away, with enough uptime in between that the old
        deadline sits beyond what ticks_diff() can resolve.  Carried over, it would
        read as 'not due yet' and leave the panel awake for the whole next away
        period; the panel must instead be able to sleep immediately."""
        state = types.SimpleNamespace(
            last_touch_time=-1,
            is_first_run=False,
            partial_update=True,
            last_minute=-1,
            display_asleep=False,
        )
        controller = self._away_controller(state)
        presence = types.SimpleNamespace(
            current_state=False,
            update=lambda *_args: False,
            flush_discord=lambda: False,
        )
        controller.presence = presence
        controller._update_display = lambda _t: None
        controller._perform_chime = lambda _t: None
        controller._update_sensor_data = lambda: None
        controller._update_weather = lambda: False
        controller._handle_date_change = lambda _day: False
        controller._check_discord_stall = lambda: None
        clock = self._patch_ticks()
        original_clear = self.module.clear_display_and_sleep
        self.addCleanup(setattr, self.module, "clear_display_and_sleep", original_clear)
        attempts = []
        failing = [True]

        def flaky_clear():
            attempts.append(True)
            if failing[0]:
                raise OSError(12)

        self.module.clear_display_and_sleep = flaky_clear

        # Away, and the panel refuses: a backoff deadline is armed.
        controller.run_main_loop()
        self.assertEqual(len(attempts), 1)
        self.assertIsNotNone(controller.display_sleep_retry_ms)

        # Back at the desk, then away again days later -- past half of the tick
        # period, which is where a carried-over deadline turns negative.
        presence.current_state = True
        controller.run_main_loop()
        clock[0] += (1 << 29) + 60 * 1000
        presence.current_state = False
        failing[0] = False
        controller.run_main_loop()

        self.assertEqual(len(attempts), 2, "the new away period must retry immediately")
        self.assertTrue(state.display_asleep)

    def _patch_ticks(self):
        """Installs MicroPython's wrapping ticks_* on the host time module.

        The real semantics, not plain arithmetic: ticks_ms() wraps at 2**30 on
        rp2 and ticks_diff() is only meaningful over half that period, which is
        precisely what a stale deadline can outlive.
        """
        period = 1 << 30
        half = period >> 1
        clock = [0]
        names = ("ticks_ms", "ticks_add", "ticks_diff")
        originals = {name: getattr(time, name, None) for name in names}

        def restore():
            for name, value in originals.items():
                if value is None:
                    if hasattr(time, name):
                        delattr(time, name)
                else:
                    setattr(time, name, value)

        self.addCleanup(restore)
        time.ticks_ms = lambda: clock[0] % period
        time.ticks_add = lambda base, delta: (base + delta) % period
        time.ticks_diff = lambda new, old: ((new - old + half) % period) - half
        return clock


class LazyImportContractTests(unittest.TestCase):
    def test_main_has_no_top_level_discord_import(self):
        source_path = Path(__file__).resolve().parents[1] / "src" / "main.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        top_level_imports = [
            node for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        self.assertFalse(
            any(
                isinstance(node, ast.ImportFrom) and node.module == "discord_notifier"
                for node in top_level_imports
            )
        )

    def test_app_controller_has_no_top_level_discord_import(self):
        source_path = Path(__file__).resolve().parents[1] / "src" / "app_controller.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        top_level_imports = [
            node for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        self.assertFalse(
            any(
                isinstance(node, ast.ImportFrom) and node.module == "discord_notifier"
                for node in top_level_imports
            )
        )

    def test_main_transfers_startup_weather_state_as_module_globals(self):
        source_path = Path(__file__).resolve().parents[1] / "src" / "main.py"
        source = source_path.read_text(encoding="utf-8")
        table = symtable.symtable(source, str(source_path), "exec")
        main_scope = next(child for child in table.get_children() if child.get_name() == "main")
        self.assertTrue(main_scope.lookup("_startup_weather_current").is_global())
        self.assertTrue(main_scope.lookup("_startup_weather_forecast").is_global())


class DiscordStallResetTests(unittest.TestCase):
    """The reboot of last resort must fire only when Discord is genuinely wedged."""

    @classmethod
    def setUpClass(cls):
        cls.module = AppControllerDateChangeTests.module
        cls.original_get_global = cls.module.config_manager.get_global
        cls.module.config_manager.get_global = lambda key, default=None: (
            "https://discord.com/api/webhooks/test/test"
            if key == "discord_webhook_url" else default
        )
        # Re-registered here rather than reused: the class above removes its own
        # discord_notifier stub in tearDownClass, and it runs first.  Without this
        # the `from discord_notifier import ...` inside _check_discord_stall() just
        # raises into its own except and the reboot-time bookkeeping goes untested.
        cls.recorded_autoreset_ips = []
        cls.original_discord_module = sys.modules.get("discord_notifier")
        discord_module = types.ModuleType("discord_notifier")
        discord_module.diag_record = lambda *_args, **_kwargs: None
        discord_module.record_autoreset_ip = lambda ip: (
            cls.recorded_autoreset_ips.append(ip) or True
        )
        sys.modules["discord_notifier"] = discord_module

    @classmethod
    def tearDownClass(cls):
        cls.module.config_manager.get_global = cls.original_get_global
        if cls.original_discord_module is None:
            sys.modules.pop("discord_notifier", None)
        else:
            sys.modules["discord_notifier"] = cls.original_discord_module

    def _controller(self, failures, pending, uptime_ms, blocked=False,
                    persist_failed=False, uptime_latched=False, current_state=False,
                    startup_discord_sent=True, lan_ip="192.168.1.50"):
        """Defaults to the away state: the cheap-reboot path the threshold targets."""
        self.recorded_autoreset_ips.clear()
        controller = object.__new__(self.module.AppController)
        controller.startup_discord_sent = startup_discord_sent
        controller.lan_ip = lan_ip
        controller.presence = types.SimpleNamespace(
            discord_mem_failures=failures,
            discord_failures=failures,
            pending_summary=pending,
            pending_session=None,
            pending_persist_failed=persist_failed,
            current_state=current_state,
        )
        controller.auto_reset_blocked = blocked
        controller.min_uptime_reached = uptime_latched
        controller.stall_checked_failures = -1
        controller.boot_ms = 0
        original_ticks_ms = getattr(time, "ticks_ms", None)
        original_ticks_diff = getattr(time, "ticks_diff", None)
        time.ticks_ms = lambda: uptime_ms
        time.ticks_diff = lambda new, old: new - old
        self.addCleanup(self._restore_ticks, original_ticks_ms, original_ticks_diff)
        return controller

    def _restore_ticks(self, original_ticks_ms, original_ticks_diff):
        if original_ticks_ms is None:
            if hasattr(time, "ticks_ms"):
                delattr(time, "ticks_ms")
        else:
            time.ticks_ms = original_ticks_ms
        if original_ticks_diff is None:
            if hasattr(time, "ticks_diff"):
                delattr(time, "ticks_diff")
        else:
            time.ticks_diff = original_ticks_diff

    def _assert_no_reset(self, controller):
        """_check_discord_stall would import machine to reboot; reaching it raises."""
        sys.modules.pop("machine", None)
        controller._check_discord_stall()

    def test_no_reset_below_the_failure_threshold(self):
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES - 1, "20260725,1,1,1,1", 60 * 60 * 1000
        )
        self._assert_no_reset(controller)

    def test_no_reset_when_nothing_is_pending(self):
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES + 5, None, 60 * 60 * 1000
        )
        self._assert_no_reset(controller)

    def test_no_reset_before_minimum_uptime(self):
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES + 5, "20260725,1,1,1,1", 60 * 1000
        )
        self._assert_no_reset(controller)

    def _presence_flush_interval_ms(self):
        """Reads the real retry interval out of presence_manager's source.

        presence_manager is mocked away in this suite and cannot be imported for
        real (it is MicroPython-only), but hardcoding the interval would let the
        test below keep passing after the actual retry cadence changes -- exactly
        the kind of silent constant drift it exists to catch.
        """
        source_path = Path(__file__).resolve().parents[1] / "src" / "presence_manager.py"
        source = source_path.read_text(encoding="utf-8")
        match = re.search(r"^DISCORD_FLUSH_INTERVAL_MS\s*=\s*(.+)$", source, re.MULTILINE)
        self.assertIsNotNone(match, "DISCORD_FLUSH_INTERVAL_MS not found in presence_manager.py")
        return self._eval_int_literal(match.group(1).strip())

    def _eval_int_literal(self, expression):
        """Evaluates an int arithmetic literal such as '60 * 1000' without exec."""
        node = ast.parse(expression, mode="eval").body

        def resolve(item):
            if isinstance(item, ast.Constant) and isinstance(item.value, int):
                return item.value
            if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Mult):
                return resolve(item.left) * resolve(item.right)
            raise AssertionError("unsupported literal: {}".format(expression))

        return resolve(node)

    def test_uptime_gate_outlasts_the_startup_window(self):
        """The gate exists to let the startup low-memory window finish its job.

        flush_startup_discord() runs at STARTUP_DISCORD_DELAY_MS and retries every
        STARTUP_DISCORD_RETRY_MS; rebooting before it has had at least one retry
        would cut short the one window measured to actually deliver.
        """
        self.assertGreater(
            self.module.DISCORD_STALL_MIN_UPTIME_MS,
            self.module.STARTUP_DISCORD_DELAY_MS + self.module.STARTUP_DISCORD_RETRY_MS,
        )

    def test_away_threshold_is_reached_faster_than_the_present_one(self):
        """Away is the cheap moment to reboot, so it must not be the slower path."""
        self.assertLess(
            self.module.DISCORD_STALL_AWAY_FAILURES,
            self.module.DISCORD_STALL_PRESENT_FAILURES,
        )

    def test_away_threshold_costs_at_most_a_few_retry_intervals(self):
        """Two attempts is the point of this path; a large value silently undoes it."""
        retry_interval_ms = self._presence_flush_interval_ms()
        wait_ms = self.module.DISCORD_STALL_AWAY_FAILURES * retry_interval_ms
        self.assertLessEqual(wait_ms, 3 * 60 * 1000)

    def test_no_reset_while_cooldown_blocks_it(self):
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES + 5,
            "20260725,1,1,1,1",
            60 * 60 * 1000,
            blocked=True,
        )
        self._assert_no_reset(controller)

    def test_no_reset_for_non_memory_failures(self):
        """A deleted webhook must never be 'fixed' by rebooting every two hours."""
        controller = self._controller(
            0, "20260725,1,1,1,1", 60 * 60 * 1000, uptime_latched=True
        )
        # Plenty of total failures, but none of them memory-related.
        controller.presence.discord_failures = 500
        controller.presence.discord_mem_failures = 0
        self._assert_no_reset(controller)

    def test_no_reset_when_pending_never_reached_flash(self):
        """Rebooting would discard a notification that only exists in RAM."""
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES + 5,
            "20260725,1,1,1,1",
            60 * 60 * 1000,
            persist_failed=True,
            uptime_latched=True,
        )
        self._assert_no_reset(controller)

    def test_uptime_latch_survives_ticks_wraparound(self):
        """ticks_diff is only valid for ~6.2 days; the latch must not un-set."""
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES,
            "20260725,1,1,1,1",
            self.module.DISCORD_STALL_MIN_UPTIME_MS + 1,
        )
        self.assertFalse(controller.min_uptime_reached)
        original_allowed = self.module.AppController._auto_reset_allowed
        try:
            # Block before rebooting, so only the latch transition is exercised.
            self.module.AppController._auto_reset_allowed = lambda _self: False
            controller._check_discord_stall()
            self.assertTrue(controller.min_uptime_reached)

            # Simulate the counter wrapping to a bogus negative difference.
            time.ticks_diff = lambda new, old: -1
            controller._check_discord_stall()
            self.assertTrue(controller.min_uptime_reached)
        finally:
            self.module.AppController._auto_reset_allowed = original_allowed

    def test_latch_is_set_before_any_stall_exists(self):
        """The latch must not wait for a stall: by then ticks_diff may be useless."""
        controller = self._controller(
            0, None, self.module.DISCORD_STALL_MIN_UPTIME_MS + 1
        )
        self.assertFalse(controller.min_uptime_reached)
        self._assert_no_reset(controller)
        self.assertTrue(controller.min_uptime_reached)

    def _count_cooldown_reads(self, controller):
        """Counts cooldown evaluations, keeping the real file I/O in the path.

        The real method runs against a fresh timestamp (so it denies the reset),
        which is what makes this a check on flash reads rather than on a stub's
        call count -- a regression back to opening the file every loop pass would
        otherwise stay invisible.
        """
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "autoreset.log"
        path.write_text(str(int(time.time())), encoding="utf-8")
        original_state_file = self.module.AUTO_RESET_STATE_FILE
        self.addCleanup(setattr, self.module, "AUTO_RESET_STATE_FILE", original_state_file)
        self.module.AUTO_RESET_STATE_FILE = str(path)

        reads = []
        original_allowed = self.module.AppController._auto_reset_allowed

        def counting_allowed(inner_self):
            reads.append(True)
            return original_allowed(inner_self)

        self.module.AppController._auto_reset_allowed = counting_allowed
        self.addCleanup(
            setattr, self.module.AppController, "_auto_reset_allowed", original_allowed
        )
        return reads

    def test_cooldown_file_is_read_once_per_failed_attempt(self):
        """While stalled the cooldown file must be read per attempt, not per loop pass."""
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES + 1,
            "20260725,1,1,1,1",
            60 * 60 * 1000,
            uptime_latched=True,
        )
        reads = self._count_cooldown_reads(controller)

        controller._check_discord_stall()
        self.assertEqual(len(reads), 1)

        # The main loop runs far more often than the ~60 s flush retry.
        controller._check_discord_stall()
        controller._check_discord_stall()
        self.assertEqual(len(reads), 1, "an unchanged failure count must not re-read")

        controller.presence.discord_mem_failures += 1
        controller._check_discord_stall()
        self.assertEqual(len(reads), 2)

    def test_a_count_that_restarts_from_zero_is_checked_again(self):
        """A successful send zeroes the counter; climbing back must not skip a check."""
        stalled = self.module.DISCORD_STALL_AWAY_FAILURES + 1
        controller = self._controller(
            stalled, "20260725,1,1,1,1", 60 * 60 * 1000, uptime_latched=True
        )
        reads = self._count_cooldown_reads(controller)

        controller._check_discord_stall()
        self.assertEqual(len(reads), 1)

        controller.presence.discord_mem_failures = 0
        controller._check_discord_stall()
        self.assertEqual(len(reads), 1, "below the threshold there is nothing to decide")

        controller.presence.discord_mem_failures = stalled
        controller._check_discord_stall()
        self.assertEqual(len(reads), 2, "the same count after a reset is a new stall")

    def test_leaving_the_desk_re_evaluates_a_count_already_checked(self):
        """The threshold drops on leaving, which is a new decision about the same
        failure count -- holding it back until the count moves would cost another
        retry interval for no reason."""
        controller = self._controller(
            self.module.DISCORD_STALL_PRESENT_FAILURES,
            "20260725,1,1,1,1",
            60 * 60 * 1000,
            uptime_latched=True,
            current_state=True,
        )
        reads = self._count_cooldown_reads(controller)

        controller._check_discord_stall()
        self.assertEqual(len(reads), 1)

        controller.presence.current_state = False
        controller._check_discord_stall()
        self.assertEqual(len(reads), 2, "a lower threshold is a new decision")

    def test_a_pending_session_alone_is_enough_to_reboot(self):
        """Session summaries are exactly the notification the away path exists for."""
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES, None, 60 * 60 * 1000
        )
        controller.presence.pending_session = "20260725,1,1,1,1"
        self.assertEqual(self._stall_check_with_reboot_available(controller), [True])

    def test_no_reset_at_the_away_threshold_while_present(self):
        """Rebooting in front of the user costs a boot screen; make it wait longer."""
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES,
            "20260725,1,1,1,1",
            60 * 60 * 1000,
            uptime_latched=True,
            current_state=True,
        )
        self._assert_no_reset(controller)

    def test_unknown_presence_uses_the_present_threshold(self):
        """current_state is None before the first update; fail towards the slow path."""
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES,
            "20260725,1,1,1,1",
            60 * 60 * 1000,
            uptime_latched=True,
            current_state=None,
        )
        self._assert_no_reset(controller)

    def test_reset_blocked_when_timestamp_cannot_be_persisted(self):
        """Fail-safe: without a durable cooldown the reboot must not happen."""
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES,
            "20260725,1,1,1,1",
            60 * 60 * 1000,
            uptime_latched=True,
        )
        original_state_file = self.module.AUTO_RESET_STATE_FILE
        try:
            self.module.AUTO_RESET_STATE_FILE = str(
                Path("no-such-dir") / "nested" / "autoreset.log"
            )
            self._assert_no_reset(controller)
            self.assertTrue(controller.auto_reset_blocked)
        finally:
            self.module.AUTO_RESET_STATE_FILE = original_state_file

    def _stall_check_with_reboot_available(self, controller):
        """Runs the check with machine.reset() mocked and a writable cooldown file."""
        import tempfile

        resets = []
        machine_module = types.ModuleType("machine")
        machine_module.reset = lambda: resets.append(True)
        sys.modules["machine"] = machine_module
        self.addCleanup(sys.modules.pop, "machine", None)
        original_state_file = self.module.AUTO_RESET_STATE_FILE
        self.addCleanup(setattr, self.module, "AUTO_RESET_STATE_FILE", original_state_file)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.module.AUTO_RESET_STATE_FILE = str(Path(directory.name) / "autoreset.log")
        controller._check_discord_stall()
        return resets

    def test_reset_fires_once_every_condition_is_met(self):
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES, "20260725,1,1,1,1", 60 * 60 * 1000
        )
        self.assertEqual(self._stall_check_with_reboot_available(controller), [True])
        # The timestamp must be persisted so the cooldown survives the reboot.
        self.assertTrue(Path(self.module.AUTO_RESET_STATE_FILE).exists())

    def test_an_announced_ip_is_noted_before_the_reboot(self):
        """The reboot buys one TLS window; re-announcing an unchanged address
        would spend it on what the user already knows instead of the backlog."""
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES, "20260725,1,1,1,1", 60 * 60 * 1000
        )
        self.assertEqual(self._stall_check_with_reboot_available(controller), [True])
        self.assertEqual(
            self.recorded_autoreset_ips, ["192.168.1.50"]
        )

    def test_an_ip_that_was_never_announced_is_not_noted(self):
        """Suppressing a notice that never went out would leave the user without
        the address entirely."""
        controller = self._controller(
            self.module.DISCORD_STALL_AWAY_FAILURES,
            "20260725,1,1,1,1",
            60 * 60 * 1000,
            startup_discord_sent=False,
        )
        self.assertEqual(self._stall_check_with_reboot_available(controller), [True])
        self.assertEqual(self.recorded_autoreset_ips, [])

    def test_reset_still_fires_while_present_at_the_slower_threshold(self):
        """The away path is not the only way out: a stuck presence reading must not
        leave notifications wedged forever."""
        controller = self._controller(
            self.module.DISCORD_STALL_PRESENT_FAILURES,
            "20260725,1,1,1,1",
            60 * 60 * 1000,
            current_state=True,
        )
        self.assertEqual(self._stall_check_with_reboot_available(controller), [True])

    def test_reset_does_not_wait_for_a_multiple_of_the_threshold(self):
        """Counts between multiples used to be ignored, doubling the wait after a
        single skipped check."""
        failures = self.module.DISCORD_STALL_AWAY_FAILURES + 1
        self.assertTrue(
            failures % self.module.DISCORD_STALL_AWAY_FAILURES,
            "pick a failure count that is not a multiple of the threshold",
        )
        controller = self._controller(failures, "20260725,1,1,1,1", 60 * 60 * 1000)
        self.assertEqual(self._stall_check_with_reboot_available(controller), [True])

    def test_cooldown_blocks_a_second_reset_within_the_window(self):
        original_state_file = self.module.AUTO_RESET_STATE_FILE
        controller = object.__new__(self.module.AppController)
        try:
            import tempfile

            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "autoreset.log"
                self.module.AUTO_RESET_STATE_FILE = str(path)

                path.write_text(str(int(time.time())), encoding="utf-8")
                self.assertFalse(controller._auto_reset_allowed())

                stale = int(time.time()) - self.module.MIN_SECONDS_BETWEEN_AUTO_RESETS - 60
                path.write_text(str(stale), encoding="utf-8")
                self.assertTrue(controller._auto_reset_allowed())

                # Fail closed: reading a corrupted timestamp as "never rebooted"
                # would drop the only boot-loop guard, and at the away threshold
                # that means a reboot every time the uptime gate opens.
                path.write_text("not-a-number", encoding="utf-8")
                self.assertFalse(controller._auto_reset_allowed())
                self.assertTrue(
                    path.read_text(encoding="utf-8").strip().isdigit(),
                    "the cooldown must be restarted, not left unreadable forever",
                )
        finally:
            self.module.AUTO_RESET_STATE_FILE = original_state_file

    def test_a_cooldown_that_cannot_be_read_blocks_the_reset(self):
        """Only a *missing* file is benign; an I/O error leaves the cooldown unknown,
        and unknown must not read as 'allowed'."""
        import tempfile

        controller = object.__new__(self.module.AppController)
        original_state_file = self.module.AUTO_RESET_STATE_FILE
        self.addCleanup(setattr, self.module, "AUTO_RESET_STATE_FILE", original_state_file)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        # A directory opens as a path but never reads as a timestamp file.
        self.module.AUTO_RESET_STATE_FILE = directory.name
        self.assertFalse(controller._auto_reset_allowed())

    def test_a_failed_cooldown_rewrite_blocks_further_resets(self):
        """Without a durable timestamp there is nothing left to stop a boot loop."""
        import tempfile

        controller = object.__new__(self.module.AppController)
        controller.auto_reset_blocked = False
        original_record = self.module.AppController._record_auto_reset
        self.addCleanup(
            setattr, self.module.AppController, "_record_auto_reset", original_record
        )
        self.module.AppController._record_auto_reset = lambda _self: False
        original_state_file = self.module.AUTO_RESET_STATE_FILE
        self.addCleanup(setattr, self.module, "AUTO_RESET_STATE_FILE", original_state_file)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "autoreset.log"
            path.write_text("not-a-number", encoding="utf-8")
            self.module.AUTO_RESET_STATE_FILE = str(path)
            self.assertFalse(controller._auto_reset_allowed())
            self.assertTrue(controller.auto_reset_blocked)

    def test_a_timestamp_ahead_of_the_current_clock_restarts_the_cooldown(self):
        """The Pico W has no battery-backed RTC: a reboot whose NTP sync failed
        restarts time.time() from the port epoch, so a timestamp written by a
        synced boot sits permanently in the future.  Read as 'not elapsed' it would
        block every future auto-reset until NTP succeeds again."""
        import tempfile

        controller = object.__new__(self.module.AppController)
        controller.auto_reset_blocked = False
        original_state_file = self.module.AUTO_RESET_STATE_FILE
        self.addCleanup(setattr, self.module, "AUTO_RESET_STATE_FILE", original_state_file)
        # A clock of its own, so the recovery can be driven forward on the new base.
        now = [1000]
        original_time = time.time
        self.addCleanup(setattr, time, "time", original_time)
        time.time = lambda: now[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "autoreset.log"
            future = now[0] + 10 * 365 * 86400
            path.write_text(str(future), encoding="utf-8")
            self.module.AUTO_RESET_STATE_FILE = str(path)

            self.assertFalse(controller._auto_reset_allowed())
            restamped = int(path.read_text(encoding="utf-8").strip())
            self.assertEqual(restamped, now[0], "the stamp must move onto the current base")
            self.assertFalse(controller.auto_reset_blocked)
            # Denied again while the restarted cooldown runs...
            self.assertFalse(controller._auto_reset_allowed())
            # ...and released once it elapses on the new base.  Without this the
            # fix would just be a different way of wedging the reboot forever.
            now[0] += self.module.MIN_SECONDS_BETWEEN_AUTO_RESETS + 1
            self.assertTrue(controller._auto_reset_allowed())

    def test_enoent_reported_without_an_errno_attribute_still_allows_the_reset(self):
        """Ports vary in how they populate OSError; args is the documented fallback.

        Getting this wrong fails closed on a device that has simply never
        auto-reset, which silently disables the recovery on its first run.
        """
        import builtins

        controller = object.__new__(self.module.AppController)
        original_open = builtins.open
        self.addCleanup(setattr, builtins, "open", original_open)

        class ArgsOnlyOSError(OSError):
            errno = None

        def args_only_open(*_args, **_kwargs):
            raise ArgsOnlyOSError(2, "ENOENT")

        builtins.open = args_only_open
        self.assertTrue(controller._auto_reset_allowed())

    def test_a_non_positive_timestamp_is_treated_as_corrupt(self):
        """A zero from a partially formatted flash is not 'the epoch'."""
        import tempfile

        controller = object.__new__(self.module.AppController)
        controller.auto_reset_blocked = False
        original_state_file = self.module.AUTO_RESET_STATE_FILE
        self.addCleanup(setattr, self.module, "AUTO_RESET_STATE_FILE", original_state_file)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "autoreset.log"
            path.write_text("0", encoding="utf-8")
            self.module.AUTO_RESET_STATE_FILE = str(path)

            self.assertFalse(controller._auto_reset_allowed())
            self.assertGreater(int(path.read_text(encoding="utf-8").strip()), 0)

    def test_missing_state_file_allows_reset(self):
        original_state_file = self.module.AUTO_RESET_STATE_FILE
        controller = object.__new__(self.module.AppController)
        try:
            self.module.AUTO_RESET_STATE_FILE = str(Path("no-such-dir") / "autoreset.log")
            self.assertTrue(controller._auto_reset_allowed())
        finally:
            self.module.AUTO_RESET_STATE_FILE = original_state_file


if __name__ == "__main__":
    unittest.main()
