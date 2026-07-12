import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.pico_image_tool.conversion import (
    ConversionOptions,
    convert_image,
    pack_mono_hlsb,
    unpack_mono_hlsb,
)


class ConversionTests(unittest.TestCase):
    def test_mono_hlsb_uses_bit_zero_for_left_pixel(self):
        image = Image.new("L", (8, 1), 0)
        image.putpixel((0, 0), 255)
        image.putpixel((2, 0), 255)
        packed = pack_mono_hlsb(image)
        self.assertEqual(packed, b"\x05")
        unpacked = unpack_mono_hlsb(packed, 8, 1)
        self.assertEqual(unpacked.tobytes(), image.tobytes())

    def test_all_targets_have_exact_device_length(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.png"
            Image.new("RGBA", (180, 120), (40, 90, 160, 180)).save(source)
            for target, expected in (("custom", 2048), ("events", 2048), ("login", 4736)):
                with self.subTest(target=target):
                    result = convert_image(source, ConversionOptions(target=target, dither="threshold"))
                    self.assertEqual(len(result.data), expected)

    def test_save_bin_writes_serial_deploy_format_marker(self):
        from tools.pico_image_tool.conversion import save_bin

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "sample.bin"
            save_bin(output, b"\x05")
            self.assertEqual(output.read_bytes(), b"\x05")
            self.assertEqual(Path(str(output) + ".hlsb").read_bytes(), b"1")

    def test_dithering_algorithms_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "gradient.png"
            gradient = Image.new("L", (128, 128))
            gradient.putdata([(x * 2 + y) % 256 for y in range(128) for x in range(128)])
            gradient.save(source)
            for algorithm in ("floyd-steinberg", "atkinson", "bayer4", "threshold"):
                options = ConversionOptions(dither=algorithm)
                first = convert_image(source, options).data
                second = convert_image(source, options).data
                self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
