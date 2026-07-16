# display_utils.py
import framebuf
import gc
import os


DISPLAY_WIDTH = 296
DISPLAY_HEIGHT = 128
NATIVE_WIDTH = 128
NATIVE_HEIGHT = 296
NATIVE_BUFFER_BYTES = NATIVE_WIDTH * NATIVE_HEIGHT // 8

_glyph_buffer = None
_glyph = None
_display_native_buffer = None
_display_native_framebuffer = None
_display_canvas = None
_display_epd = None
_image_row_buffers = {
    4: bytearray(4),
    16: bytearray(16),
    37: bytearray(37),
}


class RotatedCanvas90:
    """296x128 logical canvas backed directly by the native 128x296 buffer."""
    __slots__ = ("native", "width", "height")

    def __init__(self, native_framebuffer):
        self.native = native_framebuffer
        self.width = DISPLAY_WIDTH
        self.height = DISPLAY_HEIGHT

    def fill(self, color):
        self.native.fill(color)

    def pixel(self, x, y, color=None):
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return 1 if color is None else None
        native_x = y
        native_y = self.width - 1 - x
        if color is None:
            return self.native.pixel(native_x, native_y)
        self.native.pixel(native_x, native_y, color)

    def fill_rect(self, x, y, width, height, color):
        if width <= 0 or height <= 0:
            return
        self.native.fill_rect(y, self.width - x - width, height, width, color)


def draw_scaled_text(canvas, text, x, y, scale, color=0):
    """Draws scaled text on the canvas."""
    global _glyph_buffer, _glyph
    scale = max(1, int(scale))
    if _glyph is None:
        _glyph_buffer = bytearray(8)
        _glyph = framebuf.FrameBuffer(_glyph_buffer, 8, 8, framebuf.MONO_HLSB)
    glyph = _glyph
    for index, char in enumerate(str(text)):
        glyph.fill(1 - color)
        glyph.text(char, 0, 0, color)
        base_x = x + index * 8 * scale
        for py in range(8):
            for px in range(8):
                if glyph.pixel(px, py) != color:
                    continue
                if scale == 1:
                    canvas.pixel(base_x + px, y + py, color)
                else:
                    canvas.fill_rect(
                        base_x + px * scale,
                        y + py * scale,
                        scale,
                        scale,
                        color,
                    )

def draw_image(canvas, image_path, src_width, src_height, x, y):
    """Draws an image from a binary file onto the canvas."""
    if not image_path:
        return
    try:
        expected_length = (src_width * src_height) // 8
        actual_length = os.stat(image_path)[6]
        if actual_length != expected_length:
            print("Error: Image data length mismatch for {}. Expected {}, got {}.".format(
                image_path, expected_length, actual_length
            ))
            return
        row_bytes = (src_width + 7) // 8
        row = _image_row_buffers.get(row_bytes)
        if row is None:
            row = bytearray(row_bytes)
        bytes_read = 0
        # API uploads carry a sidecar marker for the canonical HLSB format.
        # Headerless legacy/repository assets remain MSB-left for compatibility.
        try:
            os.stat(image_path + ".hlsb")
            hlsb = True
        except OSError:
            hlsb = False
        with open(image_path, "rb") as f:
            for py in range(src_height):
                count = f.readinto(row)
                if count != row_bytes:
                    break
                bytes_read += count
                for px in range(src_width):
                    shift = px % 8 if hlsb else 7 - (px % 8)
                    value = (row[px // 8] >> shift) & 1
                    canvas.pixel(x + px, y + py, value)
        if bytes_read != expected_length:
            print(f"Error: Image read ended early for {image_path}.")
            return
    except OSError as e:
        print(f"Error: Could not read image file {image_path}. Details: {e}")
    except Exception as e:
        print(f"Error: An unexpected error occurred while processing {image_path}. Details: {e}")

def clear_region(canvas, x1, y1, x2, y2):
    """Clears a rectangular region on the canvas."""
    width = x2 - x1
    height = y2 - y1
    canvas.fill_rect(x1, y1, width, height, 1)


def release_display_workspace():
    """Releases the large display workspace before a memory-sensitive network call."""
    global _display_native_buffer, _display_native_framebuffer, _display_canvas, _display_epd
    _display_canvas = None
    _display_native_framebuffer = None
    _display_native_buffer = None
    _display_epd = None


def display_rotated_screen(draw_callback, angle=90, partial_update=False):
    """Displays content on the e-paper screen with rotation."""
    global _display_native_buffer, _display_native_framebuffer, _display_canvas, _display_epd
    from epaper import EPD_2in9
    if angle != 90:
        raise ValueError("Only the device's native 90-degree layout is supported.")
    if _display_native_framebuffer is None:
        _display_native_buffer = bytearray(NATIVE_BUFFER_BYTES)
        _display_native_framebuffer = framebuf.FrameBuffer(
            _display_native_buffer, NATIVE_WIDTH, NATIVE_HEIGHT, framebuf.MONO_HLSB
        )
        _display_canvas = RotatedCanvas90(_display_native_framebuffer)
    if _display_epd is None:
        _display_epd = EPD_2in9()

    _display_native_framebuffer.fill(1)
    draw_callback(_display_canvas)
    _display_epd.init()
    if partial_update:
        _display_epd.display_Partial(_display_native_buffer)
    else:
        _display_epd.display_Base(_display_native_buffer)
    gc.collect()
