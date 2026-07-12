import base64
import importlib.util
import json
import sys
import time
import types
import unittest
from pathlib import Path


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
            def get_global(self, path, default=None):
                return {"lan_admin.username": "admin", "lan_admin.password": "secret"}.get(path, default)

        config = types.ModuleType("config_manager")
        config.config_manager = Config()
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
        sys.modules["image_manager"] = images

        source = Path(__file__).resolve().parents[1] / "src" / "wifi_manager.py"
        spec = importlib.util.spec_from_file_location("wifi_manager_protocol_test", source)
        cls.module = importlib.util.module_from_spec(spec)
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

    def test_basic_auth_requires_exact_header(self):
        token = base64.b64encode(b"admin:secret").decode()
        request = "GET /api/v1/images HTTP/1.1\r\nAuthorization: Basic {}\r\n\r\n".format(token)
        self.assertTrue(self.module._is_lan_authorized(request))
        self.assertFalse(self.module._is_lan_authorized(request.replace(token, token + "junk")))

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
        self.assertTrue(self.module._handle_image_api(private, "GET /api/v1/images HTTP/1.1\r\n\r\n"))
        self.assertIn(b"401 Unauthorized", bytes(private.sent))


if __name__ == "__main__":
    unittest.main()
