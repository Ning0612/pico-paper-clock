import random
import unittest

from pathlib import Path
import tempfile

from tools.pico_image_tool.image_codec import (
    compress,
    decompress,
    encode_if_smaller,
    is_compressed,
    write_image,
)


class ImageCodecTests(unittest.TestCase):
    def test_round_trip_preserves_payload_and_bit_order(self):
        data = bytes((index * 17 + index // 11) % 256 for index in range(2048))
        encoded = compress(data, hlsb=True)
        decoded, hlsb = decompress(encoded, len(data))
        self.assertEqual(decoded, data)
        self.assertTrue(hlsb)

    def test_round_trip_supports_legacy_msb_bit_order(self):
        data = b"\x80\x01" * 1024
        encoded = compress(data, hlsb=False)
        decoded, hlsb = decompress(encoded, len(data))
        self.assertEqual(decoded, data)
        self.assertFalse(hlsb)

    def test_codec_uses_self_describing_ppc1_when_compression_is_not_smaller(self):
        data = random.Random(12345).randbytes(2048)
        encoded = encode_if_smaller(data)
        self.assertTrue(is_compressed(encoded))
        decoded, hlsb = decompress(encoded, len(data))
        self.assertEqual(decoded, data)
        self.assertTrue(hlsb)

    def test_write_image_removes_stale_sidecar(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "sample.bin"
            marker = Path(str(output) + ".hlsb")
            marker.write_bytes(b"1")

            stored = write_image(output, b"\x05", hlsb=True)

            self.assertTrue(is_compressed(stored))
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
