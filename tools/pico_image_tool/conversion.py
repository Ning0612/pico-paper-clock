from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageOps


TARGET_SPECS = {
    "custom": (128, 128),
    "events": (128, 128),
    "login": (296, 128),
}

DITHER_ALGORITHMS = ("floyd-steinberg", "atkinson", "bayer4", "threshold")
FIT_MODES = ("cover", "contain", "stretch")


def _pixels(image: Image.Image):
    getter = getattr(image, "get_flattened_data", None)
    return getter() if getter else image.getdata()


@dataclass(frozen=True)
class ConversionOptions:
    target: str = "custom"
    fit: str = "cover"
    dither: str = "floyd-steinberg"
    threshold: int = 128
    invert: bool = False
    focus_x: float = 0.5
    focus_y: float = 0.5


@dataclass(frozen=True)
class ConversionResult:
    preview: Image.Image
    data: bytes
    width: int
    height: int


def _validate_options(options: ConversionOptions) -> Tuple[int, int]:
    if options.target not in TARGET_SPECS:
        raise ValueError(f"Unsupported target: {options.target}")
    if options.fit not in FIT_MODES:
        raise ValueError(f"Unsupported fit mode: {options.fit}")
    if options.dither not in DITHER_ALGORITHMS:
        raise ValueError(f"Unsupported dithering algorithm: {options.dither}")
    if not 0 <= options.threshold <= 255:
        raise ValueError("Threshold must be between 0 and 255.")
    if not 0.0 <= options.focus_x <= 1.0 or not 0.0 <= options.focus_y <= 1.0:
        raise ValueError("Crop focus must be between 0.0 and 1.0.")
    return TARGET_SPECS[options.target]


def _open_on_white(path: str | Path) -> Image.Image:
    with Image.open(path) as source:
        source = ImageOps.exif_transpose(source)
        rgba = source.convert("RGBA")
    white = Image.new("RGBA", rgba.size, "white")
    white.alpha_composite(rgba)
    return white.convert("L")


def _fit_image(image: Image.Image, size: Tuple[int, int], options: ConversionOptions) -> Image.Image:
    if options.fit == "stretch":
        return image.resize(size, Image.Resampling.LANCZOS)
    if options.fit == "contain":
        contained = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
        output = Image.new("L", size, 255)
        output.paste(contained, ((size[0] - contained.width) // 2, (size[1] - contained.height) // 2))
        return output
    return ImageOps.fit(
        image,
        size,
        Image.Resampling.LANCZOS,
        centering=(options.focus_x, options.focus_y),
    )


def _atkinson(image: Image.Image, threshold: int) -> Image.Image:
    width, height = image.size
    pixels = [float(value) for value in _pixels(image)]
    offsets = ((1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2))
    for y in range(height):
        row = y * width
        for x in range(width):
            index = row + x
            old = pixels[index]
            new = 255.0 if old >= threshold else 0.0
            pixels[index] = new
            error = (old - new) / 8.0
            for dx, dy in offsets:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and ny < height:
                    target = ny * width + nx
                    pixels[target] = min(255.0, max(0.0, pixels[target] + error))
    output = Image.new("L", (width, height))
    output.putdata([int(value) for value in pixels])
    return output


def _bayer4(image: Image.Image, threshold: int) -> Image.Image:
    matrix = (
        (0, 8, 2, 10),
        (12, 4, 14, 6),
        (3, 11, 1, 9),
        (15, 7, 13, 5),
    )
    width, height = image.size
    source = list(_pixels(image))
    output = []
    bias = threshold - 128
    for y in range(height):
        for x in range(width):
            ordered_threshold = matrix[y & 3][x & 3] * 16 + 8 + bias
            output.append(255 if source[y * width + x] >= ordered_threshold else 0)
    result = Image.new("L", (width, height))
    result.putdata(output)
    return result


def _dither(image: Image.Image, options: ConversionOptions) -> Image.Image:
    if options.dither == "floyd-steinberg":
        return image.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    if options.dither == "atkinson":
        return _atkinson(image, options.threshold)
    if options.dither == "bayer4":
        return _bayer4(image, options.threshold)
    return image.point(lambda value: 255 if value >= options.threshold else 0, mode="L")


def pack_mono_hlsb(image: Image.Image) -> bytes:
    """Pack a black/white image with bit 0 representing the left-most pixel."""
    mono = image.convert("L")
    width, height = mono.size
    if width % 8:
        raise ValueError("MONO_HLSB width must be divisible by 8.")
    source = mono.load()
    packed = bytearray(width * height // 8)
    output_index = 0
    for y in range(height):
        for byte_x in range(width // 8):
            value = 0
            for bit in range(8):
                if source[byte_x * 8 + bit, y] >= 128:
                    value |= 1 << bit
            packed[output_index] = value
            output_index += 1
    return bytes(packed)


def unpack_mono_hlsb(data: bytes, width: int, height: int) -> Image.Image:
    if len(data) != width * height // 8:
        raise ValueError("Packed image length does not match dimensions.")
    output = Image.new("L", (width, height), 255)
    pixels = output.load()
    index = 0
    for y in range(height):
        for byte_x in range(width // 8):
            value = data[index]
            index += 1
            for bit in range(8):
                pixels[byte_x * 8 + bit, y] = 255 if value & (1 << bit) else 0
    return output


def convert_image(path: str | Path, options: ConversionOptions) -> ConversionResult:
    size = _validate_options(options)
    image = _fit_image(_open_on_white(path), size, options)
    if options.invert:
        image = ImageOps.invert(image)
    preview = _dither(image, options)
    return ConversionResult(preview=preview, data=pack_mono_hlsb(preview), width=size[0], height=size[1])


def save_bin(path: str | Path, data: bytes) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    Path(str(output) + ".hlsb").write_bytes(b"1")
    return output
