# display_utils.py
import framebuf
import gc

def get_pixel(buf, x, y, width):
    """Gets the pixel value from a framebuffer."""
    bytes_per_line = width // 8
    index = (x // 8) + y * bytes_per_line
    bit = 7 - (x % 8)
    return 0 if ((buf[index] >> bit) & 0x01) == 0 else 1

def set_pixel(buf, x, y, width, color):
    """Sets the pixel value in a framebuffer."""
    bytes_per_line = width // 8
    index = (x // 8) + y * bytes_per_line
    bit = 7 - (x % 8)
    if color == 0:
        buf[index] &= ~(1 << bit)
    else:
        buf[index] |= (1 << bit)

def rotate_buffer_270(src, src_width, src_height):
    """Rotates a framebuffer 270 degrees clockwise."""
    dest_width = src_height
    dest = bytearray(len(src))
    for i in range(len(dest)):
        dest[i] = 0xff
    for y in range(src_height):
        for x in range(src_width):
            dx = (src_height - 1) - y
            dy = x
            pixel = get_pixel(src, x, y, src_width)
            set_pixel(dest, dx, dy, dest_width, pixel)
    return dest

def rotate_buffer_180(src, src_width, src_height):
    """Rotates a framebuffer 180 degrees clockwise."""
    dest = bytearray(len(src))
    for i in range(len(dest)):
        dest[i] = 0xff
    for y in range(src_height):
        for x in range(src_width):
            dx = (src_width - 1) - x
            dy = (src_height - 1) - y
            pixel = get_pixel(src, x, y, src_width)
            set_pixel(dest, dx, dy, src_width, pixel)
    return dest

def rotate_buffer_90_clockwise(src, src_width, src_height):
    """Rotates a framebuffer 90 degrees clockwise."""
    dest_width = src_height
    dest = bytearray(len(src))
    for i in range(len(dest)):
        dest[i] = 0xff
    for y in range(src_height):
        for x in range(src_width):
            dx = y
            dy = (src_width - 1) - x
            pixel = get_pixel(src, x, y, src_width)
            set_pixel(dest, dx, dy, dest_width, pixel)
    return dest

def rotate_buffer(src, src_width, src_height, angle):
    """Rotates a framebuffer by a specified angle."""
    if angle == 90:
        return rotate_buffer_90_clockwise(src, src_width, src_height)
    elif angle == 180:
        return rotate_buffer_180(src, src_width, src_height)
    elif angle == 270:
        return rotate_buffer_270(src, src_width, src_height)
    else:
        raise ValueError("Unsupported rotation angle")

def draw_scaled_text(canvas, text, x, y, scale, color=0):
    """Draws scaled text on the canvas."""
    if scale == 1:
        canvas.text(text, x, y, color)
        return

    orig_char_width = 8
    orig_char_height = 8
    orig_width = len(text) * orig_char_width
    orig_height = orig_char_height

    temp_buf = bytearray((orig_width * orig_height) // 8)
    temp_fb = framebuf.FrameBuffer(temp_buf, orig_width, orig_height, framebuf.MONO_HLSB)
    temp_fb.fill(0xff)
    temp_fb.text(text, 0, 0, color)

    scaled_width = orig_width * scale
    scaled_height = orig_height * scale
    scaled_buf = bytearray((scaled_width * scaled_height) // 8)
    for i in range(len(scaled_buf)):
        scaled_buf[i] = 0xff

    for py in range(orig_height):
        for px in range(orig_width):
            p = temp_fb.pixel(px, py)
            if p == 0:
                for sy in range(scale):
                    for sx in range(scale):
                        set_pixel(scaled_buf, px * scale + sx, py * scale + sy, scaled_width, 0)
    scaled_fb = framebuf.FrameBuffer(scaled_buf, scaled_width, scaled_height, framebuf.MONO_HLSB)
    canvas.blit(scaled_fb, x, y)

    temp_fb = None
    temp_buf = None
    scaled_fb = None
    scaled_buf = None
    gc.collect()

def draw_image(canvas, image_path, src_width, src_height, x, y):
    """Draws an image from a binary file onto the canvas."""
    img_buf = None
    img_fb = None
    try:
        expected_length = (src_width * src_height) // 8
        img_buf = bytearray(expected_length)
        with open(image_path, "rb") as f:
            bytes_read = f.readinto(img_buf)
        if bytes_read != expected_length:
            print(f"Error: Image data length mismatch for {image_path}. Expected {expected_length}, got {bytes_read}.")
            return
        img_fb = framebuf.FrameBuffer(img_buf, src_width, src_height, framebuf.MONO_HLSB)
        canvas.blit(img_fb, x, y)
    except OSError as e:
        print(f"Error: Could not read image file {image_path}. Details: {e}")
    except Exception as e:
        print(f"Error: An unexpected error occurred while processing {image_path}. Details: {e}")
    finally:
        img_buf = None
        img_fb = None
        gc.collect()

def clear_region(canvas, x1, y1, x2, y2):
    """Clears a rectangular region on the canvas."""
    width = x2 - x1
    height = y2 - y1
    canvas.fill_rect(x1, y1, width, height, 1)

def display_rotated_screen(draw_callback, angle=90, partial_update=False):
    """Displays content on the e-paper screen with rotation."""
    from epaper import EPD_2in9
    if angle in [90, 270]:
        canvas_width = 296
        canvas_height = 128
    elif angle == 180:
        canvas_width = 128
        canvas_height = 296
    else:
        raise ValueError("Unsupported rotation angle: {}".format(angle))
    canvas_buf = bytearray(canvas_width * canvas_height // 8)
    canvas = framebuf.FrameBuffer(canvas_buf, canvas_width, canvas_height, framebuf.MONO_HLSB)
    for i in range(len(canvas_buf)):
        canvas_buf[i] = 0xff
    draw_callback(canvas)
    native_buf = rotate_buffer(canvas_buf, canvas_width, canvas_height, angle)
    epd = EPD_2in9()
    epd.init()
    if partial_update:
        epd.display_Partial(native_buf)
    else:
        epd.display_Base(native_buf)
    canvas_buf = None
    native_buf = None
    canvas = None
    epd = None
    gc.collect()
