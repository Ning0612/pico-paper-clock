import gzip
import unittest

from tools.build_html import deterministic_gzip


class BuildHtmlTests(unittest.TestCase):
    def test_gzip_header_is_platform_neutral(self):
        payload = deterministic_gzip(b"<!doctype html><p>ok</p>")

        self.assertEqual(payload[:10], b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff")
        self.assertEqual(gzip.decompress(payload), b"<!doctype html><p>ok</p>")


if __name__ == "__main__":
    unittest.main()
