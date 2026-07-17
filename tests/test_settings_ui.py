import gzip
import unittest
from pathlib import Path


class SettingsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.source = (root / "tools" / "html_src" / "settings.html").read_text(encoding="utf-8")
        cls.asset = gzip.decompress((root / "src" / "html" / "settings.bin").read_bytes()).decode("utf-8")

    def test_presence_timeout_fields_are_loaded_and_submitted(self):
        for content in (self.source, self.asset):
            self.assertIn('name="presence_leave_timeout_sec"', content)
            self.assertIn('name="presence_return_timeout_sec"', content)
            self.assertIn("離開書桌判定時間（秒）", content)
            self.assertIn("恢復在席判定時間（秒）", content)
            self.assertIn("setValue('presenceLeaveTimeout',u.presence_leave_timeout_sec)", content)
            self.assertIn("setValue('presenceReturnTimeout',u.presence_return_timeout_sec)", content)


if __name__ == "__main__":
    unittest.main()
