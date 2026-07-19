"""Host-side codec for the compact at-rest image format."""

from pathlib import Path


MAGIC = b"PPC1"
HEADER_SIZE = 8
WINDOW_SIZE = 256
MIN_MATCH = 3
MAX_MATCH = 258
HLSB_FLAG = 0x01


def _header(length: int, hlsb: bool) -> bytes:
    if not 0 <= length <= 0xFFFF:
        raise ValueError("Image payload is too large for PPC1 format.")
    flags = HLSB_FLAG if hlsb else 0
    return MAGIC + bytes((flags, length & 0xFF, (length >> 8) & 0xFF, 0))


def _parse_header(data: bytes, expected_length: int | None = None) -> tuple[int, bool]:
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        raise ValueError("Image is not a PPC1 compressed payload.")
    flags = data[4]
    if flags & ~HLSB_FLAG:
        raise ValueError("Unsupported PPC1 image flags.")
    length = data[5] | (data[6] << 8)
    if expected_length is not None and length != expected_length:
        raise ValueError(f"Expected {expected_length} uncompressed bytes, got {length}.")
    return length, bool(flags & HLSB_FLAG)


def is_compressed(data: bytes) -> bool:
    return len(data) >= HEADER_SIZE and data[:4] == MAGIC


def _find_match(data: bytes, position: int) -> tuple[int, int]:
    start = max(0, position - WINDOW_SIZE)
    remaining = len(data) - position
    best_offset = 0
    best_length = 0
    for candidate in range(start, position):
        offset = position - candidate
        limit = min(MAX_MATCH, remaining)
        length = 0
        while length < limit:
            source = candidate + length
            if source >= position:
                source = candidate + ((source - candidate) % offset)
            if data[source] != data[position + length]:
                break
            length += 1
        if length > best_length:
            best_offset = offset
            best_length = length
    return best_offset, best_length


def compress(data: bytes, hlsb: bool = True) -> bytes:
    """Encode bytes as PPC1 using a 256-byte streaming LZ window."""
    payload = bytearray()
    position = 0
    while position < len(data):
        flag_index = len(payload)
        payload.append(0)
        flags = 0
        for bit in range(8):
            if position >= len(data):
                break
            offset, length = _find_match(data, position)
            if length >= MIN_MATCH:
                # Zero offset means the full 256-byte window distance.
                payload.append(offset & 0xFF)
                payload.append(length - MIN_MATCH)
                position += length
            else:
                flags |= 1 << bit
                payload.append(data[position])
                position += 1
        payload[flag_index] = flags
    return _header(len(data), hlsb) + bytes(payload)


def decompress(data: bytes, expected_length: int | None = None) -> tuple[bytes, bool]:
    """Decode PPC1 data, returning uncompressed bytes and its bit order."""
    length, hlsb = _parse_header(data, expected_length)
    output = bytearray()
    history = bytearray(WINDOW_SIZE)
    history_pos = 0
    history_count = 0
    position = HEADER_SIZE
    flags = 0
    bits_left = 0

    def push(value: int) -> None:
        nonlocal history_pos, history_count
        history[history_pos] = value
        history_pos = (history_pos + 1) & (WINDOW_SIZE - 1)
        history_count = min(WINDOW_SIZE, history_count + 1)

    while len(output) < length:
        if bits_left == 0:
            if position >= len(data):
                raise ValueError("PPC1 payload ended before the image was decoded.")
            flags = data[position]
            position += 1
            bits_left = 8
        literal = flags & 1
        flags >>= 1
        bits_left -= 1
        if literal:
            if position >= len(data):
                raise ValueError("PPC1 literal is truncated.")
            value = data[position]
            position += 1
            output.append(value)
            push(value)
            continue

        if position + 2 > len(data):
            raise ValueError("PPC1 match is truncated.")
        offset_code = data[position]
        match_length = data[position + 1] + MIN_MATCH
        position += 2
        offset = WINDOW_SIZE if offset_code == 0 else offset_code
        if offset > history_count:
            raise ValueError("PPC1 match points before the decoded image.")
        source = (history_pos - offset) & (WINDOW_SIZE - 1)
        for _ in range(match_length):
            if len(output) >= length:
                raise ValueError("PPC1 match exceeds the declared image length.")
            value = history[source]
            source = (source + 1) & (WINDOW_SIZE - 1)
            output.append(value)
            push(value)

    return bytes(output), hlsb


def encode_ppc1(data: bytes, hlsb: bool = True) -> bytes:
    """Return a PPC1 payload, even when it is larger than the raw payload."""
    return compress(data, hlsb=hlsb)


def encode_if_smaller(data: bytes, hlsb: bool = True) -> bytes:
    """Backward-compatible alias for the PPC1-only image output policy."""
    return encode_ppc1(data, hlsb=hlsb)


def write_image(path: str | Path, data: bytes, hlsb: bool = True) -> bytes:
    """Write a self-describing PPC1 image and remove any stale sidecar."""
    output = Path(path)
    stored = encode_ppc1(data, hlsb=hlsb)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(stored)
    marker = Path(str(output) + ".hlsb")
    try:
        marker.unlink()
    except FileNotFoundError:
        pass
    return stored
