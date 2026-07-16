import json
import ipaddress
import subprocess
import threading
from unittest.mock import Mock, patch
from urllib.parse import parse_qs
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.pico_image_tool.client import DeviceClient, DeviceError, DeviceInfo, _ping_host, discover, local_24_subnets


class Handler(BaseHTTPRequestHandler):
    request_record = None
    setup_required = False

    def log_message(self, *_):
        pass

    def _json(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_json(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", "session=test-session; Path=/; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/v1/device":
            self._json(200, {"device": "pi-paper-clock", "api_version": 1, "heap_free": 1234, "fs_free": 5678})
        elif self.path == "/api/v1/auth/status":
            self._json(200, {"setup_required": Handler.setup_required, "authenticated": False, "csrf_token": "pre-auth"})
        else:
            self._json(200, {"items": [], "fs_free": 5678})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = parse_qs(self.rfile.read(length).decode())
        if self.path == "/api/v1/auth/login":
            self.assert_auth = body
            self._auth_json(200, {"authenticated": True, "csrf_token": "session-csrf", "redirect": "/"})
        else:
            self._json(200, {})

    def do_PUT(self):
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        Handler.request_record = (self.path, dict(self.headers), body)
        self._json(201, {"path": "/image/custom/test.bin", "bytes": length, "replaced": False})


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host = f"127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_device_info_contract(self):
        info = DeviceClient(self.host).info()
        self.assertEqual(info.api_version, 1)
        self.assertEqual(info.fs_free, 5678)

    def test_upload_path_headers_body_and_progress(self):
        progress = []
        data = b"\x5a" * 2048
        DeviceClient(self.host).upload(data, "custom", "test.bin", overwrite=True, preview=True,
                                       progress=lambda sent, total: progress.append((sent, total)))
        path, headers, received = Handler.request_record
        self.assertEqual(path, "/api/v1/images/custom/test.bin?overwrite=1&preview=1")
        self.assertEqual(headers["X-Pico-Clock-API"], "1")
        self.assertEqual(headers["Cookie"], "session=test-session")
        self.assertEqual(headers["X-CSRF-Token"], "session-csrf")
        self.assertEqual(received, data)
        self.assertEqual(progress[-1], (2048, 2048))

    def test_image_tool_requires_webui_first_setup(self):
        Handler.setup_required = True
        try:
            with self.assertRaises(DeviceError) as context:
                DeviceClient(self.host).list_images("custom")
            self.assertEqual(context.exception.code, "setup_required")
        finally:
            Handler.setup_required = False

    @patch("tools.pico_image_tool.client.os.name", "nt")
    @patch("tools.pico_image_tool.client.subprocess.run")
    def test_windows_network_probes_hide_console_windows(self, run):
        class FakeStartupInfo:
            def __init__(self):
                self.dwFlags = 0
                self.wShowWindow = None

        run.return_value = Mock(returncode=0)

        with patch.object(subprocess, "STARTUPINFO", FakeStartupInfo, create=True), \
                patch.object(subprocess, "STARTF_USESHOWWINDOW", 0x00000001, create=True), \
                patch.object(subprocess, "SW_HIDE", 0, create=True), \
                patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            self.assertEqual(_ping_host("192.168.1.114", 0.5), "192.168.1.114")

        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["creationflags"], 0x08000000)
        self.assertEqual(kwargs["startupinfo"].dwFlags, 0x00000001)
        self.assertEqual(kwargs["startupinfo"].wShowWindow, 0)

    @patch("tools.pico_image_tool.client.DeviceClient.info")
    @patch("tools.pico_image_tool.client.subprocess.run")
    def test_discover_prefers_arp_candidates(self, run, info):
        run.return_value = Mock(
            stdout=(
                "  192.168.1.1      60-83-e7-31-ea-60    dynamic\n"
                "  192.168.1.114    28-cd-c1-05-f0-db    dynamic\n"
            )
        )
        info.return_value = DeviceInfo("192.168.1.114", 1, 1234, 5678)

        devices = discover(["192.168.1.114/32"], timeout=5.0, workers=1)

        self.assertEqual([device.host for device in devices], ["192.168.1.114"])
        self.assertEqual(info.call_count, 1)
        run.assert_called_once()

    @patch("tools.pico_image_tool.client.DeviceClient.info")
    @patch("tools.pico_image_tool.client._arp_hosts")
    @patch("tools.pico_image_tool.client._ping_host", return_value="192.168.1.3")
    def test_discover_falls_back_when_arp_cache_misses_device(self, ping_host, arp_hosts, info):
        arp_hosts.return_value = [ipaddress.ip_address("192.168.1.1")]
        info.side_effect = [
            DeviceError("not a Pi Paper Clock"),
            DeviceInfo("192.168.1.3", 1, 1234, 5678),
        ]

        devices = discover(["192.168.1.0/29"], timeout=0.1, workers=4, first_only=True)

        self.assertEqual([device.host for device in devices], ["192.168.1.3"])
        self.assertGreaterEqual(info.call_count, 2)

    @patch("tools.pico_image_tool.client.socket.getaddrinfo")
    def test_local_subnets_skip_loopback_and_link_local(self, getaddrinfo):
        getaddrinfo.return_value = [
            (None, None, None, None, ("127.0.0.1", 0)),
            (None, None, None, None, ("169.254.83.20", 0)),
            (None, None, None, None, ("192.168.1.20", 0)),
        ]

        self.assertEqual([str(network) for network in local_24_subnets()], ["192.168.1.0/24"])


if __name__ == "__main__":
    unittest.main()
