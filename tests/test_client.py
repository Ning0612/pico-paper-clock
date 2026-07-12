import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.pico_image_tool.client import DeviceClient


class Handler(BaseHTTPRequestHandler):
    request_record = None

    def log_message(self, *_):
        pass

    def _json(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/v1/device":
            self._json(200, {"device": "pi-paper-clock", "api_version": 1, "heap_free": 1234, "fs_free": 5678})
        else:
            self._json(200, {"items": [], "fs_free": 5678})

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
        self.assertTrue(headers["Authorization"].startswith("Basic "))
        self.assertEqual(received, data)
        self.assertEqual(progress[-1], (2048, 2048))


if __name__ == "__main__":
    unittest.main()

