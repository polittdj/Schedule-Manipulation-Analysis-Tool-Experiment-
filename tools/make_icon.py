"""Generate ``launch/icon.ico`` (pure standard library, no image deps).

A 64x64 32-bit icon: a navy badge with white schedule bars and one red "critical"
bar -- the flat-bitmap cousin of ``launch/icon.svg``. Reproducible: run
``python tools/make_icon.py`` from the repo root to regenerate the .ico.
"""

from __future__ import annotations

import struct
from pathlib import Path

SIZE = 64
_BG = (0x1A, 0x3A, 0x5A)  # navy (R, G, B)
_WHITE = (0xEA, 0xF2, 0xFB)
_RED = (0xC0, 0x39, 0x2B)

# Horizontal "schedule" bars in top-down pixel coords: (x0, y0, x1, y1, colour).
_BARS: list[tuple[int, int, int, int, tuple[int, int, int]]] = [
    (10, 12, 40, 19, _WHITE),
    (14, 25, 50, 32, _RED),  # the critical bar
    (18, 38, 44, 45, _WHITE),
    (12, 51, 38, 58, _WHITE),
]


def _colour_at(x: int, y: int) -> tuple[int, int, int]:
    for x0, y0, x1, y1, colour in _BARS:
        if x0 <= x < x1 and y0 <= y < y1:
            return colour
    return _BG


def build_ico() -> bytes:
    # XOR image: 32-bit BGRA, bottom-up rows.
    xor = bytearray()
    for y in range(SIZE - 1, -1, -1):
        for x in range(SIZE):
            r, g, b = _colour_at(x, y)
            xor += bytes((b, g, r, 255))
    # AND mask: 1 bit/pixel, rows padded to 4 bytes; all zero (opaque via alpha).
    row_bytes = ((SIZE + 31) // 32) * 4
    and_mask = bytes(row_bytes * SIZE)

    bitmapinfoheader = struct.pack(
        "<IiiHHIIiiII", 40, SIZE, SIZE * 2, 1, 32, 0, len(xor), 0, 0, 0, 0
    )
    image = bitmapinfoheader + bytes(xor) + and_mask

    icondir = struct.pack("<HHH", 0, 1, 1)  # reserved, type=icon, count=1
    entry = struct.pack("<BBBBHHII", SIZE, SIZE, 0, 0, 1, 32, len(image), 6 + 16)
    return icondir + entry + image


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "launch" / "icon.ico"
    out.write_bytes(build_ico())
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
