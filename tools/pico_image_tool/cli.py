import argparse
import json
import re
import sys
from pathlib import Path

from .client import DeviceClient, DeviceError, discover
from .conversion import ConversionOptions, DITHER_ALGORITHMS, FIT_MODES, TARGET_SPECS, convert_image, save_bin


def _safe_filename(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(value).stem).strip("_") or "image"
    return stem[:48] + ".bin"


def _conversion_options(args) -> ConversionOptions:
    return ConversionOptions(
        target=args.type,
        fit=args.fit,
        dither=args.dither,
        threshold=args.threshold,
        invert=args.invert,
        focus_x=args.focus_x,
        focus_y=args.focus_y,
    )


def _add_conversion_options(parser):
    parser.add_argument("--type", choices=TARGET_SPECS, default="custom")
    parser.add_argument("--fit", choices=FIT_MODES, default="cover")
    parser.add_argument("--dither", choices=DITHER_ALGORITHMS, default="floyd-steinberg")
    parser.add_argument("--threshold", type=int, default=128)
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--focus-x", type=float, default=0.5)
    parser.add_argument("--focus-y", type=float, default=0.5)


def _add_device_options(parser):
    parser.add_argument("--device", required=True, help="Device IPv4 address or HTTP host.")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds.")
    parser.add_argument("--event", help="MMDD or birthday when --type events is selected.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pico-image-tool", description="Convert and manage Pi Paper Clock images.")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("gui", help="Open the desktop GUI.")
    discovery = commands.add_parser("discover", help="Find Pi Paper Clock devices on local /24 networks.")
    discovery.add_argument("--subnet", action="append", help="CIDR subnet; may be repeated and must be /24 or smaller.")
    discovery.add_argument("--timeout", type=float, default=0.35)

    convert = commands.add_parser("convert", help="Convert an image to canonical MONO_HLSB .bin.")
    convert.add_argument("input")
    convert.add_argument("--output")
    _add_conversion_options(convert)

    upload = commands.add_parser("upload", help="Convert, preserve locally, and upload an image.")
    upload.add_argument("input")
    upload.add_argument("--output", help="Local .bin path; defaults beside the source image.")
    upload.add_argument("--name", help="Remote .bin filename.")
    upload.add_argument("--overwrite", action="store_true")
    upload.add_argument("--preview", action="store_true")
    _add_conversion_options(upload)
    _add_device_options(upload)

    listing = commands.add_parser("list", help="List images on the device.")
    listing.add_argument("--type", choices=TARGET_SPECS, default="custom")
    _add_device_options(listing)

    delete = commands.add_parser("delete", help="Delete one device image.")
    delete.add_argument("name")
    delete.add_argument("--type", choices=TARGET_SPECS, default="custom")
    _add_device_options(delete)

    preview = commands.add_parser("preview", help="Preview an existing device image.")
    preview.add_argument("name")
    preview.add_argument("--type", choices=TARGET_SPECS, default="custom")
    _add_device_options(preview)
    return parser


def _client(args) -> DeviceClient:
    return DeviceClient(args.device, args.username, args.password, timeout=args.timeout)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "gui":
            from .gui import run_gui
            run_gui()
            return 0
        if args.command == "discover":
            devices = discover(args.subnet, args.timeout)
            for device in devices:
                print(f"{device.host}\tAPI {device.api_version}\theap={device.heap_free}\tfs={device.fs_free}")
            return 0 if devices else 2
        if args.command == "convert":
            result = convert_image(args.input, _conversion_options(args))
            output = Path(args.output) if args.output else Path(args.input).with_suffix(".bin")
            save_bin(output, result.data)
            print(f"{output}\t{len(result.data)} bytes\t{result.width}x{result.height}")
            return 0
        if args.command == "upload":
            source = Path(args.input)
            expected = TARGET_SPECS[args.type][0] * TARGET_SPECS[args.type][1] // 8
            if source.suffix.lower() == ".bin":
                marker = Path(str(source) + ".hlsb")
                if not marker.is_file():
                    raise ValueError("Raw .bin upload requires the adjacent .bin.hlsb format marker.")
                data = source.read_bytes()
                if len(data) != expected:
                    raise ValueError(f"Expected {expected} bytes for {args.type}, got {len(data)}.")
                output = source
            else:
                result = convert_image(source, _conversion_options(args))
                data = result.data
                output = Path(args.output) if args.output else source.with_suffix(".bin")
                save_bin(output, data)
            name = args.name or _safe_filename(source.name)
            if not name.endswith(".bin"):
                name += ".bin"
            response = _client(args).upload(data, args.type, name, args.event, args.overwrite, args.preview)
            print(json.dumps({"local": str(output), **response}, ensure_ascii=False))
            return 0
        if args.command == "list":
            print(json.dumps(_client(args).list_images(args.type, args.event), ensure_ascii=False, indent=2))
            return 0
        if args.command == "delete":
            print(json.dumps(_client(args).delete(args.type, args.name, args.event), ensure_ascii=False))
            return 0
        if args.command == "preview":
            print(json.dumps(_client(args).preview(args.type, args.name, args.event), ensure_ascii=False))
            return 0
    except (OSError, ValueError, DeviceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 1
