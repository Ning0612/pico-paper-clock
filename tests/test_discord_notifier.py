import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


class DiscordNotifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ("network", "config_manager")
        cls.original_modules = {name: sys.modules.get(name) for name in names}

        network = types.ModuleType("network")
        network.STA_IF = 0
        network.WLAN = lambda _interface: types.SimpleNamespace(isconnected=lambda: False)
        sys.modules["network"] = network

        config_module = types.ModuleType("config_manager")
        config_module.config_manager = types.SimpleNamespace(
            get_global=lambda _key, default="": default,
        )
        sys.modules["config_manager"] = config_module

        source = Path(__file__).resolve().parents[1] / "src" / "discord_notifier.py"
        spec = importlib.util.spec_from_file_location("discord_notifier_test", source)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_json_payload_escapes_controls_and_keeps_utf8_emoji(self):
        message = 'quote " slash \\ newline\n tab\t 中文🟦'
        payload = self.module._discord_payload(message)

        self.assertEqual(json.loads(payload.decode("utf-8")), {"content": message})
        self.assertIn("🟦".encode("utf-8"), payload)
        self.assertEqual(len(payload), len(payload.decode("utf-8").encode("utf-8")))

    def test_write_all_handles_partial_writes_without_copying_payload(self):
        class PartialSocket:
            def __init__(self):
                self.received = bytearray()

            def write(self, data):
                chunk = bytes(data[:2])
                self.received.extend(chunk)
                return len(chunk)

        sock = PartialSocket()
        self.module._write_all(sock, bytearray(b"abcdef"))
        self.assertEqual(sock.received, b"abcdef")

    def test_presence_embed_uses_exact_progress_colors_and_inline_fields(self):
        payload = self.module._presence_summary_embed_payload(
            "20260714", 51840, 7800, 4
        )
        embed = json.loads(payload.decode("utf-8"))["embeds"][0]

        self.assertEqual(embed["title"], "📊 在席日報 · 2026-07-14")
        self.assertEqual(embed["description"], "🟨🟨🟨🟨🟨🟨⬜⬜⬜⬜  60%")
        self.assertEqual(embed["color"], 15132194)
        self.assertEqual([field["name"] for field in embed["fields"]], ["書桌前", "最長一次", "次數"])
        self.assertTrue(all(field["inline"] for field in embed["fields"]))

    def test_progress_handles_negative_and_over_target_values(self):
        progress, percent, color = self.module._presence_progress(-1)
        self.assertEqual((progress, percent, color), ("⬜" * 10, 0, 15158332))

        progress, percent, color = self.module._presence_progress(86400 * 12)
        self.assertEqual((progress, percent, color), ("🟩" * 10, 999, 3066993))

    def test_presence_session_message_uses_shared_l1_format(self):
        message = self.module._presence_session_message(
            "20260714", "090500", "20260715", "101500", 4200
        )
        self.assertEqual(message, "📖 書桌前時段結束\n09:05 → 10:15（1h 10m）")


if __name__ == "__main__":
    unittest.main()
