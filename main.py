#!/usr/bin/env python3
"""Writes the 23 November 2026 news page to /output/entry.png.

The picture beside this file is the entry. This program does not just copy it
blind: it walks the PNG chunk by chunk, checks every CRC against the bytes it
just read, checks the header the chunks describe, and refuses to hand the file
over unless it meets this contest's limits. A file that fails those checks
would be listed with a 0 and take no prize, so failing loudly is better than
writing something invalid.

Run outside the grader with MAKEFUN_OUTPUT_DIR standing in for /output.
"""

import os
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "entry.png"

MAX_BYTES = 1024 * 1024
MAX_SIDE = 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# The chunk types a whole, non-interlaced PNG of this shape carries.
KNOWN = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"sRGB", b"pHYs", b"iCCP", b"bKGD", b"tEXt"}


class BadImage(Exception):
    """The image breaks a rule of the contest, and the entry cannot be sent."""


def walk_chunks(blob):
    """Yields (type, data) for every chunk, verifying each length and CRC."""
    if not blob.startswith(PNG_MAGIC):
        raise BadImage("the file does not begin with the PNG signature")
    at = len(PNG_MAGIC)
    total = len(blob)
    seen_iend = False
    while at < total:
        if at + 8 > total:
            raise BadImage(f"truncated chunk header at byte {at}")
        (length,) = struct.unpack(">I", blob[at:at + 4])
        kind = blob[at + 4:at + 8]
        body_end = at + 8 + length
        if body_end + 4 > total:
            raise BadImage(f"chunk {kind!r} runs past the end of the file")
        body = blob[at + 8:body_end]
        (recorded,) = struct.unpack(">I", blob[body_end:body_end + 4])
        actual = zlib.crc32(kind + body) & 0xFFFFFFFF
        if actual != recorded:
            raise BadImage(f"chunk {kind!r} fails its checksum ({actual:#x} != {recorded:#x})")
        if kind not in KNOWN:
            # An unknown-but-ancillary chunk is legal; an unknown critical one is not.
            if kind[0:1].isupper():
                raise BadImage(f"unknown critical chunk {kind!r}")
        yield kind, body
        at = body_end + 4
        if kind == b"IEND":
            seen_iend = True
            break
    if not seen_iend:
        raise BadImage("the file has no IEND chunk")
    if at != total:
        raise BadImage(f"{total - at} bytes follow IEND")


def read_header(blob):
    """The IHDR must be the first chunk and describe a picture within the limits."""
    for kind, body in walk_chunks(blob):
        if kind != b"IHDR":
            raise BadImage("the first chunk is not IHDR")
        if len(body) != 13:
            raise BadImage("IHDR is not 13 bytes")
        width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", body)
        if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
            raise BadImage(f"{width}x{height} is outside {MAX_SIDE}x{MAX_SIDE}")
        if interlace != 0:
            raise BadImage("interlaced images are not written here")
        return width, height, depth, colour
    raise BadImage("no IHDR chunk")


def check_pixels(width, height, depth, colour, idat):
    """Inflates the image data and checks it is exactly the rows the header promises.

    A PNG can carry a valid CRC on every chunk and still describe fewer rows than
    its header claims; the gate reads the picture, so this matters. Each row is one
    filter byte followed by width * channels samples.
    """
    channels = 4 if colour == 6 else 3
    stride = 1 + width * channels * (depth // 8)
    try:
        raw = zlib.decompress(idat)
    except zlib.error as exc:
        raise BadImage(f"the image data does not inflate: {exc}") from exc
    expected = stride * height
    if len(raw) != expected:
        raise BadImage(f"the image data holds {len(raw)} bytes, not the {expected} its header describes")
    # Every row begins with a filter type from 0 to 4; anything else is not a PNG.
    for row in range(height):
        kind = raw[row * stride]
        if kind > 4:
            raise BadImage(f"row {row} carries filter type {kind}")


def check(blob):
    """Returns a summary once the image passes every rule, else raises."""
    if not blob:
        raise BadImage("the image is empty")
    if len(blob) > MAX_BYTES:
        raise BadImage(f"{len(blob)} bytes is over the {MAX_BYTES} cap")
    width, height, depth, colour = read_header(blob)
    if depth != 8:
        raise BadImage(f"bit depth {depth} is not 8")
    if colour not in (2, 6):
        raise BadImage(f"colour type {colour} is not truecolour")
    idat = b""
    for kind, body in walk_chunks(blob):
        if kind == b"IDAT":
            idat += body
    if not idat:
        raise BadImage("the file carries no image data")
    check_pixels(width, height, depth, colour, idat)
    return width, height, len(blob), len(idat)


def main():
    out_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    try:
        blob = SOURCE.read_bytes()
    except OSError as exc:
        print(f"cannot read {SOURCE}: {exc}", file=sys.stderr)
        return 1
    try:
        width, height, size, pixels = check(blob)
    except BadImage as exc:
        print(f"entry.png is not enterable: {exc}", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "entry.png"
    # Write beside the target and swap it in, so a reader never sees half a file.
    staging = target.with_suffix(".png.part")
    staging.write_bytes(blob)
    os.replace(staging, target)
    written = target.read_bytes()
    if written != blob:
        print("the file written does not match the source", file=sys.stderr)
        return 1
    print(f"wrote {target}: {width}x{height}, {size} bytes, {pixels} bytes of image data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
