import importlib.util
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
import gzip


class FakeClient:
    def __init__(self, lines=()):
        self.lines = list(lines)
        self.sent = bytearray()
        self.timeouts = []
        self.read_calls = 0

    def makefile(self, *_args):
        return self

    def readline(self):
        return self.lines.pop(0) if self.lines else b""

    def send(self, data):
        self.sent.extend(data)
        return len(data)

    def settimeout(self, value):
        self.timeouts.append(value)

    def readinto(self, _buffer, _length=None):
        self.read_calls += 1
        return 0


class BodyClient(FakeClient):
    def __init__(self, body=b""):
        super().__init__()
        self.body = bytearray(body)

    def readinto(self, buffer, length=None):
        size = min(len(self.body), length if length is not None else len(buffer))
        if size:
            buffer[:size] = self.body[:size]
            del self.body[:size]
        self.read_calls += 1
        return size


class WifiProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = (
            "network", "machine", "ujson", "ubinascii", "gc", "display_manager",
            "config_manager", "chime", "hardware_manager", "presence_manager", "image_manager",
        )
        cls.original_modules = {name: sys.modules.get(name) for name in names}
        cls.original_ticks = {
            name: getattr(time, name, None) for name in ("ticks_ms", "ticks_add", "ticks_diff")
        }
        time.ticks_ms = lambda: 1000
        time.ticks_add = lambda value, delta: value + delta
        time.ticks_diff = lambda new, old: new - old

        network = types.ModuleType("network")
        network.STA_IF = 0
        network.AP_IF = 1
        sys.modules["network"] = network

        machine = types.ModuleType("machine")
        machine.Pin = lambda value: value
        machine.ADC = lambda _pin: types.SimpleNamespace(read_u16=lambda: 7)
        machine.reset = lambda: None
        sys.modules["machine"] = machine
        sys.modules["ujson"] = json
        sys.modules["ubinascii"] = __import__("binascii")

        fake_gc = types.ModuleType("gc")
        fake_gc.collect = lambda: None
        fake_gc.mem_free = lambda: 12345
        sys.modules["gc"] = fake_gc

        display = types.ModuleType("display_manager")
        display.update_display_Restart = lambda: None
        display.update_display_AP = lambda: None
        sys.modules["display_manager"] = display

        class Config:
            values = {
                "lan_admin.username": "admin",
                "lan_admin.password": "",
                "setup_complete": False,
            }
            profile = {
                "name": "Home",
                "wifi": {"ssid": "", "password": ""},
            }
            last_profile_update = None

            def get_global(self, path, default=None):
                return self.values.get(path, default)

            def set_global(self, path, value):
                self.values[path] = value

            def get_profile(self, name):
                return self.profile if name == self.profile["name"] else None

            def apply_profile_update(self, original_name, profile_data, **_kwargs):
                self.last_profile_update = (original_name, profile_data)
                self.profile = profile_data

        config = types.ModuleType("config_manager")
        config.config_manager = Config()
        cls.config = config.config_manager
        sys.modules["config_manager"] = config

        chime = types.ModuleType("chime")
        chime.Chime = object
        sys.modules["chime"] = chime
        hardware = types.ModuleType("hardware_manager")
        hardware.HardwareManager = object
        sys.modules["hardware_manager"] = hardware
        presence = types.ModuleType("presence_manager")
        presence.get_presence_manager = lambda: None
        presence.iter_lines = lambda _path: iter(())
        sys.modules["presence_manager"] = presence

        class StoreError(Exception):
            def __init__(self, code, message):
                super().__init__(message)
                self.code = code
                self.message = message

        images = types.ModuleType("image_manager")
        images.IMAGE_SPECS = {"custom": (128, 128, 2048)}
        images.ImageStoreError = StoreError
        images.filesystem_free = lambda: 98765
        images.image_store = types.SimpleNamespace(catalog_generation=0)
        images.image_directory = lambda *_args: None
        images.image_store.iter_images = lambda *_args: iter(())
        images.validate_event = lambda _value: None
        sys.modules["image_manager"] = images

        source = Path(__file__).resolve().parents[1] / "src" / "wifi_manager.py"
        spec = importlib.util.spec_from_file_location("wifi_manager_protocol_test", source)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_unquote_preserves_unescaped_utf8_text(self):
        self.assertEqual(self.module.unquote("名稱+Taipei"), "名稱 Taipei")
        self.assertEqual(
            self.module.parse_query_string("label=在席"),
            {"label": "在席"},
        )

    def test_html_asset_response_advertises_gzip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "page.bin"
            payload = gzip.compress(b"<!doctype html><p>ok</p>", mtime=0)
            path.write_bytes(payload)
            client = FakeClient()
            self.module._send_html_file(client, str(path))
            self.assertIn(b"Content-Encoding: gzip\r\n", client.sent)
            self.assertTrue(client.sent.endswith(payload))

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

    def test_basic_auth_is_not_accepted_and_session_cookie_is_exact(self):
        self.module._clear_session()
        basic = "GET /api/v1/images HTTP/1.1\r\nAuthorization: Basic abc\r\n\r\n"
        self.assertFalse(self.module._is_lan_authorized(basic))
        token, csrf = self.module._start_session()
        request = "GET /api/v1/images HTTP/1.1\r\nCookie: {}={};\r\n\r\n".format(
            self.module.SESSION_COOKIE_NAME, token
        )
        self.assertTrue(self.module._is_lan_authorized(request))
        self.assertFalse(self.module._is_lan_authorized(request.replace(token, token + "junk")))
        self.assertTrue(self.module._request_csrf_valid(
            request + "X-CSRF-Token: {}\r\n".format(csrf)
        ))

    def test_password_record_uses_pbkdf2_and_session_expires(self):
        original_calibration = self.module._calibrate_pbkdf2_iterations
        self.module._calibrate_pbkdf2_iterations = lambda: 64
        try:
            record = self.module._password_hash("correct horse battery staple")
        finally:
            self.module._calibrate_pbkdf2_iterations = original_calibration

        self.assertTrue(record.startswith("pbkdf2-sha256$64$"))
        self.assertTrue(self.module._password_matches("correct horse battery staple", record))
        self.assertFalse(self.module._password_matches("wrong password", record))

        self.module._clear_session()
        token, _ = self.module._start_session()
        request = "GET /api/v1/config HTTP/1.1\r\nCookie: {}={}\r\n\r\n".format(
            self.module.SESSION_COOKIE_NAME, token
        )
        self.assertTrue(self.module._is_lan_authorized(request))
        original_ticks = time.ticks_ms
        try:
            time.ticks_ms = lambda: 1000 + self.module.SESSION_IDLE_TIMEOUT_MS + 1
            self.assertFalse(self.module._is_lan_authorized(request))
        finally:
            time.ticks_ms = original_ticks
            self.module._clear_session()

    def test_login_creates_session_and_logout_revokes_it(self):
        self.config.values["lan_admin.password"] = ""
        self.config.values["setup_complete"] = False
        self.module._clear_session()
        self.module._LOGIN_FAILURES.clear()
        original_calibration = self.module._calibrate_pbkdf2_iterations
        self.module._calibrate_pbkdf2_iterations = lambda: 64
        try:
            body = "password=correct123&password_confirm=correct123&csrf_token={}".format(
                self.module.CSRF_TOKEN
            ).encode()
            request = "POST /api/v1/auth/login HTTP/1.1\r\nContent-Length: {}\r\n\r\n".format(len(body))
            self.module._REQUEST_DEADLINE = self.module._request_now_ms() + 5000
            response = BodyClient(body)
            self.assertTrue(self.module._handle_auth_api(response, request, "127.0.0.1"))
            self.assertIn(b"200 OK", bytes(response.sent))
            self.assertIn(
                ("Set-Cookie: {}=".format(self.module.SESSION_COOKIE_NAME)).encode(),
                bytes(response.sent),
            )
            self.assertIn(b'"authenticated": true', bytes(response.sent))
            self.assertEqual(self.module._admin_username(), "admin")
            token = self.module._CURRENT_SESSION_TOKEN
            csrf = self.module._SESSION_CSRF_TOKEN
            self.assertTrue(self.config.values["lan_admin.password"].startswith("pbkdf2-sha256$64$"))

            session_request = "GET /api/v1/auth/session HTTP/1.1\r\nCookie: {}={}\r\n\r\n".format(
                self.module.SESSION_COOKIE_NAME, token
            )
            session_response = BodyClient()
            self.assertTrue(self.module._handle_auth_api(session_response, session_request, "127.0.0.1"))
            self.assertIn(b'"authenticated": true', bytes(session_response.sent))

            logout_request = (
                "POST /api/v1/auth/logout HTTP/1.1\r\n"
                "Cookie: {}={}\r\nX-CSRF-Token: {}\r\n\r\n"
            ).format(self.module.SESSION_COOKIE_NAME, token, csrf)
            logout_response = BodyClient()
            self.assertTrue(self.module._handle_auth_api(logout_response, logout_request, "127.0.0.1"))
            self.assertIsNone(self.module._CURRENT_SESSION_TOKEN)
            self.assertIn(b"Max-Age=0", bytes(logout_response.sent))
        finally:
            self.module._calibrate_pbkdf2_iterations = original_calibration
            self.module._clear_session()
            self.config.values["lan_admin.password"] = ""
            self.config.values["setup_complete"] = False

    def test_login_redirect_rejects_external_and_control_character_targets(self):
        self.assertEqual(self.module._safe_redirect("/dashboard"), "/dashboard")
        self.assertEqual(self.module._safe_redirect("//evil.example"), "/")
        self.assertEqual(self.module._safe_redirect("/\\\\evil.example"), "/")
        self.assertEqual(self.module._safe_redirect("/dashboard\r\nX-Test: injected"), "/")

    def test_duplicate_length_and_transfer_encoding_are_rejected_before_body_read(self):
        for headers in (
            "Content-Length: 2\r\nContent-Length: 2",
            "Content-Length: 2\r\nTransfer-Encoding: chunked",
        ):
            with self.subTest(headers=headers):
                client = FakeClient()
                request = "POST /api/v1/config HTTP/1.1\r\n{}\r\n\r\n".format(headers)
                with self.assertRaises(ValueError):
                    self.module._read_request_body(client, request)
                self.assertEqual(client.read_calls, 0)

    def test_incomplete_header_returns_408_with_total_deadline(self):
        client = FakeClient([b"GET / HTTP/1.1\r\n", b"Host: device\r\n"])
        self.assertIsNone(self.module._read_http_request(client))
        self.assertIn(b"408 Request Timeout", bytes(client.sent))
        self.assertTrue(client.timeouts)

    def test_device_discovery_is_public_but_image_routes_require_auth(self):
        public = FakeClient()
        self.assertTrue(self.module._handle_image_api(public, "GET /api/v1/device HTTP/1.1\r\n\r\n"))
        self.assertIn(b"200 OK", bytes(public.sent))

        private = FakeClient()
        self.assertTrue(self.module._handle_image_api(private, "GET /api/v1/images HTTP/1.1\r\n\r\n", require_auth=True))
        self.assertIn(b"401 Unauthorized", bytes(private.sent))

    def test_image_mutations_require_session_before_initial_setup(self):
        client = FakeClient()
        request = (
            "POST /api/v1/images/custom/sample/preview HTTP/1.1\r\n"
            "X-Pico-Clock-API: 1\r\n\r\n"
        )
        self.assertTrue(self.module._handle_image_api(client, request, require_auth=False))
        self.assertIn(b"401 Unauthorized", bytes(client.sent))

    def test_presence_stream_skips_malformed_lines(self):
        original_manager = self.module.get_presence_manager
        original_iter_lines = self.module.iter_lines
        try:
            self.module.get_presence_manager = lambda: object()
            self.module.iter_lines = lambda _path: iter((
                "malformed-event",
                "20260714,123000,1,321",
            ))
            client = FakeClient()
            self.module._send_presence_lines(client, "events")
            response = bytes(client.sent)
            self.assertIn(b"200 OK", response)
            self.assertIn(b'"d":"20260714"', response)
            self.assertTrue(response.endswith(b"]"))
        finally:
            self.module.get_presence_manager = original_manager
            self.module.iter_lines = original_iter_lines

    def test_desk_sessions_are_derived_without_adc_debug_fields(self):
        original_manager = self.module.get_presence_manager
        original_iter_lines = self.module.iter_lines
        original_presence_epoch = self.module._presence_epoch
        try:
            event_epochs = {"120000": 100, "121500": 1000, "122000": 1300, "123000": 1900}
            self.module._presence_epoch = lambda _date, event_time: event_epochs[event_time]
            end_epoch = event_epochs["123000"]
            self.module.get_presence_manager = lambda: types.SimpleNamespace(
                get_status=lambda: {"state": 1, "now_epoch": end_epoch}
            )
            self.module.iter_lines = lambda _path: iter((
                "20260714,120000,1,321",
                "20260714,121500,0,654",
                "20260714,122000,1,333",
            ))
            sessions = self.module._presence_sessions()
            self.assertEqual(sessions[0], {
                "sd": "20260714", "st": "120000",
                "ed": "20260714", "et": "121500", "sec": 900,
            })
            self.assertEqual(sessions[1]["st"], "122000")
            expected_end = time.localtime(end_epoch)
            self.assertEqual(
                sessions[1]["et"],
                "{:02d}{:02d}{:02d}".format(expected_end[3], expected_end[4], expected_end[5]),
            )
            self.assertEqual(sessions[1]["sec"], 600)
            self.assertNotIn("a", sessions[0])
        finally:
            self.module.get_presence_manager = original_manager
            self.module.iter_lines = original_iter_lines
            self.module._presence_epoch = original_presence_epoch

    def test_config_save_preserves_presence_timeout(self):
        self.config.last_profile_update = None
        params = {
            "original_profile_name": "Home",
            "profile_name": "Home",
            "ssid": "",
            "password": "",
            "location": "Taipei",
            "birthday": "0101",
            "light_threshold": "20000",
            "presence_timeout_min": "7",
            "image_interval_min": "2",
            "timezone_offset": "8",
            "chime_interval": "hourly",
            "chime_pitch": "880",
            "chime_volume": "80",
        }
        self.module._save_settings_from_params(params)

        self.assertIsNotNone(self.config.last_profile_update)
        self.assertEqual(
            self.config.last_profile_update[1]["user"]["presence_timeout_min"],
            7,
        )

        params["presence_timeout_min"] = "0"
        with self.assertRaises(ValueError):
            self.module._save_settings_from_params(params)
        params["presence_timeout_min"] = "61"
        with self.assertRaises(ValueError):
            self.module._save_settings_from_params(params)


if __name__ == "__main__":
    unittest.main()
