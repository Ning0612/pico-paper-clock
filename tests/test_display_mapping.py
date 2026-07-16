import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path

from tools.pico_image_tool.image_codec import compress


class NativeBuffer:
    def __init__(self):
        self.pixels = {}
        self.rectangles = []

    def fill(self, color):
        self.fill_color = color

    def pixel(self, x, y, color=None):
        if color is None:
            return self.pixels.get((x, y), 1)
        self.pixels[(x, y)] = color

    def fill_rect(self, x, y, width, height, color):
        self.rectangles.append((x, y, width, height, color))


class LogicalCanvas:
    def __init__(self):
        self.pixels = {}

    def pixel(self, x, y, color):
        self.pixels[(x, y)] = color


class TestFrameBuffer:
    def __init__(self, buffer, width, height, format):
        self.buffer = buffer
        self.width = width
        self.height = height
        self.format = format

    def fill(self, color):
        self.fill_color = color


class TestEpd:
    instances = []

    def __init__(self):
        self.init_calls = 0
        self.base_buffers = []
        TestEpd.instances.append(self)

    def init(self):
        self.init_calls += 1

    def display_Base(self, buffer):
        self.base_buffers.append(buffer)


class DisplayMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake = types.ModuleType("framebuf")
        fake.MONO_HLSB = 0
        fake.FrameBuffer = object
        sys.modules.setdefault("framebuf", fake)
        src = str(Path(__file__).resolve().parents[1] / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        cls.module = importlib.import_module("display_utils")

    def test_rotated_canvas_maps_corners_and_rectangles(self):
        native = NativeBuffer()
        canvas = self.module.RotatedCanvas90(native)
        canvas.pixel(0, 0, 0)
        canvas.pixel(295, 127, 0)
        canvas.fill_rect(10, 20, 30, 40, 0)
        self.assertEqual(native.pixels[(0, 295)], 0)
        self.assertEqual(native.pixels[(127, 0)], 0)
        self.assertEqual(native.rectangles[-1], (20, 256, 40, 30, 0))

    def test_image_reader_uses_hlsb_bit_zero_on_left_for_marked_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "row.bin"
            path.write_bytes(b"\x05")
            Path(str(path) + ".hlsb").write_bytes(b"1")
            canvas = LogicalCanvas()
            self.module.draw_image(canvas, str(path), 8, 1, 0, 0)
            white = [x for x in range(8) if canvas.pixels[(x, 0)] == 1]
            self.assertEqual(white, [0, 2])

    def test_existing_unmarked_asset_keeps_legacy_msb_left_order(self):
        with tempfile.TemporaryDirectory() as temp:
            asset = Path(temp) / "legacy.bin"
            asset.write_bytes(bytes(index % 256 for index in range(2048)))
            canvas = LogicalCanvas()
            self.module.draw_image(canvas, str(asset), 128, 128, 0, 0)
            data = asset.read_bytes()
            expected_first_row = [1 if data[x // 8] & (1 << (7 - x % 8)) else 0 for x in range(128)]
            self.assertEqual([canvas.pixels[(x, 0)] for x in range(128)], expected_first_row)

    def test_compressed_asset_uses_header_bit_order(self):
        with tempfile.TemporaryDirectory() as temp:
            asset = Path(temp) / "compressed.bin"
            raw = bytes((index * 29) % 256 for index in range(2048))
            asset.write_bytes(compress(raw, hlsb=True))
            canvas = LogicalCanvas()
            self.module.draw_image(canvas, str(asset), 128, 128, 0, 0)
            expected_first_row = [1 if raw[x // 8] & (1 << (x % 8)) else 0 for x in range(128)]
            self.assertEqual([canvas.pixels[(x, 0)] for x in range(128)], expected_first_row)

    def test_display_workspace_is_reused_across_updates(self):
        original_framebuffer = self.module.framebuf.FrameBuffer
        original_epaper = sys.modules.get("epaper")
        original_values = (
            self.module._display_native_buffer,
            self.module._display_native_framebuffer,
            self.module._display_canvas,
            self.module._display_epd,
        )
        fake_epaper = types.ModuleType("epaper")
        fake_epaper.EPD_2in9 = TestEpd
        self.module.framebuf.FrameBuffer = TestFrameBuffer
        sys.modules["epaper"] = fake_epaper
        TestEpd.instances = []
        canvases = []
        try:
            self.module._display_native_buffer = None
            self.module._display_native_framebuffer = None
            self.module._display_canvas = None
            self.module._display_epd = None
            self.module.display_rotated_screen(lambda canvas: canvases.append(canvas))
            first_buffer = self.module._display_native_buffer
            first_canvas = self.module._display_canvas
            self.module.display_rotated_screen(lambda canvas: canvases.append(canvas))

            self.assertIs(self.module._display_native_buffer, first_buffer)
            self.assertIs(self.module._display_canvas, first_canvas)
            self.assertEqual(len(TestEpd.instances), 1)
            self.assertEqual(TestEpd.instances[0].init_calls, 2)
            self.assertIs(canvases[0], canvases[1])
            self.assertIs(TestEpd.instances[0].base_buffers[0], first_buffer)
            self.assertIs(TestEpd.instances[0].base_buffers[1], first_buffer)
            self.module.release_display_workspace()
            self.assertIsNone(self.module._display_native_buffer)
            self.assertIsNone(self.module._display_native_framebuffer)
            self.assertIsNone(self.module._display_canvas)
            self.assertIsNone(self.module._display_epd)
        finally:
            self.module.framebuf.FrameBuffer = original_framebuffer
            if original_epaper is None:
                sys.modules.pop("epaper", None)
            else:
                sys.modules["epaper"] = original_epaper
            (
                self.module._display_native_buffer,
                self.module._display_native_framebuffer,
                self.module._display_canvas,
                self.module._display_epd,
            ) = original_values


if __name__ == "__main__":
    unittest.main()
