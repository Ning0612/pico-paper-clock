import random
import unittest

from tools.pico_image_tool.image_codec import compress, decompress, encode_if_smaller


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

    def test_codec_keeps_raw_when_compression_is_not_smaller(self):
        data = random.Random(12345).randbytes(2048)
        self.assertEqual(encode_if_smaller(data), data)


if __name__ == "__main__":
    unittest.main()
