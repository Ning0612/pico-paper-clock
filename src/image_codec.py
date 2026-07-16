"""Streaming decoder for PPC1 compressed bitmap files."""

import os


MAGIC = b"PPC1"
HEADER_SIZE = 8
WINDOW_SIZE = 256
MIN_MATCH = 3
HLSB_FLAG = 0x01
INPUT_BUFFER_BYTES = 512


def parse_header(header, expected_length=None):
    if len(header) < HEADER_SIZE or header[:4] != MAGIC:
        raise ValueError("Image is not a PPC1 compressed payload.")
    flags = header[4]
    if flags & ~HLSB_FLAG:
        raise ValueError("Unsupported PPC1 image flags.")
    length = header[5] | (header[6] << 8)
    if expected_length is not None and length != expected_length:
        raise ValueError("PPC1 uncompressed length does not match image dimensions.")
    return length, bool(flags & HLSB_FLAG)


class CompressedReader:
    """Decode PPC1 into caller-owned row buffers using a 256-byte history."""
    __slots__ = (
        "file", "expected_length", "input", "input_pos", "input_count",
        "flags", "bits_left", "history", "history_pos", "history_count",
        "pending_length", "pending_source", "output_count",
    )

    def __init__(self, file_obj, expected_length, header):
        parse_header(header, expected_length)
        self.file = file_obj
        self.expected_length = expected_length
        self.input = bytearray(INPUT_BUFFER_BYTES)
        self.input_pos = 0
        self.input_count = 0
        self.flags = 0
        self.bits_left = 0
        self.history = bytearray(WINDOW_SIZE)
        self.history_pos = 0
        self.history_count = 0
        self.pending_length = 0
        self.pending_source = 0
        self.output_count = 0

    def _read_byte(self):
        if self.input_pos >= self.input_count:
            try:
                count = self.file.readinto(self.input)
            except AttributeError:
                chunk = self.file.read(INPUT_BUFFER_BYTES)
                count = len(chunk)
                if count:
                    self.input[:count] = chunk
            if not count:
                raise ValueError("PPC1 payload ended unexpectedly.")
            self.input_pos = 0
            self.input_count = count
        value = self.input[self.input_pos]
        self.input_pos += 1
        return value

    def _push(self, value):
        self.history[self.history_pos] = value
        self.history_pos = (self.history_pos + 1) & (WINDOW_SIZE - 1)
        if self.history_count < WINDOW_SIZE:
            self.history_count += 1

    def _next_value(self):
        if self.pending_length:
            value = self.history[self.pending_source]
            self.pending_source = (self.pending_source + 1) & (WINDOW_SIZE - 1)
            self.pending_length -= 1
            self._push(value)
            return value

        if self.bits_left == 0:
            self.flags = self._read_byte()
            self.bits_left = 8
        literal = self.flags & 1
        self.flags >>= 1
        self.bits_left -= 1
        if literal:
            value = self._read_byte()
            self._push(value)
            return value

        offset_code = self._read_byte()
        length = self._read_byte() + MIN_MATCH
        offset = WINDOW_SIZE if offset_code == 0 else offset_code
        if offset > self.history_count:
            raise ValueError("PPC1 match points before the decoded image.")
        self.pending_source = (self.history_pos - offset) & (WINDOW_SIZE - 1)
        self.pending_length = length
        return self._next_value()

    def readinto(self, target):
        if self.output_count >= self.expected_length:
            return 0
        count = 0
        limit = min(len(target), self.expected_length - self.output_count)
        while count < limit:
            target[count] = self._next_value()
            count += 1
            self.output_count += 1
        return count


def inspect_file(path, expected_length):
    """Return (compressed, hlsb) after checking only file metadata/header."""
    actual_length = os.stat(path)[6]
    with open(path, "rb") as file_obj:
        prefix = file_obj.read(4)
        if prefix == MAGIC:
            header = prefix + file_obj.read(HEADER_SIZE - len(prefix))
            _, hlsb = parse_header(header, expected_length)
            return True, hlsb
    if actual_length == expected_length:
        return False, False
    raise ValueError("Image length does not match raw or PPC1 format.")


def validate_file(path, expected_length):
    """Validate a raw or PPC1 image using bounded memory."""
    compressed, hlsb = inspect_file(path, expected_length)
    if not compressed:
        return False, False
    with open(path, "rb") as file_obj:
        header = file_obj.read(HEADER_SIZE)
        reader = CompressedReader(file_obj, expected_length, header)
        scratch = bytearray(min(INPUT_BUFFER_BYTES, expected_length))
        remaining = expected_length
        while remaining:
            count = reader.readinto(scratch)
            if not count:
                raise ValueError("PPC1 payload ended before the image was decoded.")
            remaining -= count
        if reader.pending_length:
            raise ValueError("PPC1 match exceeds the declared image length.")
    return True, hlsb


def compressed_reader(file_obj, expected_length):
    """Read a PPC1 header from an open file and return (reader, hlsb)."""
    header = file_obj.read(HEADER_SIZE)
    _, hlsb = parse_header(header, expected_length)
    return CompressedReader(file_obj, expected_length, header), hlsb
