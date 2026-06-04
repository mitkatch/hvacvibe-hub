#!/usr/bin/env python3
"""
screenshot.py — Capture Pi Waveshare display framebuffer and save as JPEG/PNG.

Usage on Pi:
    python3 screenshot.py                    # saves to /tmp/screenshot.jpg
    python3 screenshot.py /tmp/myshot.png    # saves as PNG

Usage on Windows (convert raw file):
    python3 screenshot.py --convert fb_snapshot.raw display.jpg

Capture steps:
    1. On Pi:      sudo cat /dev/fb0 > /tmp/screenshot.raw
    2. On Windows: scp mitkatch@hvacvibe.local:/tmp/screenshot.raw .
    3. On Windows: python3 screenshot.py --convert screenshot.raw display.jpg
"""

import sys
import os
import argparse

# ── Display geometry (must match your setup) ───────────────────────────────
FB_DEVICE  = "/dev/waveshare"
FB_W       = 480      # framebuffer physical width  (after rotation)
FB_H       = 320      # framebuffer physical height (after rotation)
RAW_W      = 320      # raw framebuffer width  (portrait, pre-rotation)
RAW_H      = 480      # raw framebuffer height (portrait, pre-rotation)
ROTATE_DEG = 90       # degrees display.py rotates before writing


def capture_on_pi(output_path: str, fb_device: str = FB_DEVICE):
    """
    Read framebuffer directly on Pi and save as image.
    Must be run as root or with fb read permissions.
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("Install dependencies: pip install pillow numpy --break-system-packages")
        sys.exit(1)

    print(f"Reading {fb_device}...")
    try:
        with open(fb_device, "rb") as f:
            raw = f.read(RAW_W * RAW_H * 2)   # RGB565 = 2 bytes/pixel
    except PermissionError:
        print(f"Permission denied — try: sudo python3 {sys.argv[0]}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"Framebuffer {FB_DEVICE} not found")
        sys.exit(1)

    img = _rgb565_to_image(raw, RAW_W, RAW_H)

    # Rotate to match display orientation
    if ROTATE_DEG:
        img = img.rotate(-ROTATE_DEG, expand=True)

    _save(img, output_path)


def convert_raw(raw_path: str, output_path: str):
    """
    Convert a raw framebuffer file (captured via cat /dev/fb0 > file)
    to a viewable image. Run this on Windows/Mac after scp.
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("Install dependencies: pip install pillow numpy")
        sys.exit(1)

    print(f"Converting {raw_path}...")
    with open(raw_path, "rb") as f:
        raw = f.read(RAW_W * RAW_H * 2)

    img = _rgb565_to_image(raw, RAW_W, RAW_H)

    if ROTATE_DEG:
        img = img.rotate(-ROTATE_DEG, expand=True)

    _save(img, output_path)


def _rgb565_to_image(raw: bytes, w: int, h: int):
    """Convert RGB565 bytes to PIL Image."""
    import numpy as np
    from PIL import Image

    arr = np.frombuffer(raw, dtype=np.uint16).reshape((h, w))
    r = ((arr & 0xF800) >> 11) << 3
    g = ((arr & 0x07E0) >> 5)  << 2
    b = (arr  & 0x001F)        << 3
    rgb = np.stack([r, g, b], axis=2).astype(np.uint8)
    return Image.fromarray(rgb)


def _save(img, path: str):
    fmt = "JPEG" if path.lower().endswith((".jpg", ".jpeg")) else "PNG"
    if fmt == "JPEG":
        img.save(path, "JPEG", quality=92)
    else:
        img.save(path)
    print(f"Saved: {path}  ({img.width}x{img.height})")


def main():
    parser = argparse.ArgumentParser(
        description="Capture or convert Pi Waveshare display framebuffer"
    )
    parser.add_argument(
        "output", nargs="?", default="/tmp/screenshot.jpg",
        help="Output file path (default: /tmp/screenshot.jpg)"
    )
    parser.add_argument(
        "--convert", metavar="RAW_FILE",
        help="Convert a raw framebuffer file instead of capturing live"
    )
    parser.add_argument(
        "--fb", default=FB_DEVICE,
        help=f"Framebuffer device (default: {FB_DEVICE})"
    )
    args = parser.parse_args()

    global FB_DEVICE
    FB_DEVICE = args.fb

    if args.convert:
        convert_raw(args.convert, args.output)
    else:
        capture_on_pi(args.output, fb_device=args.fb)


if __name__ == "__main__":
    main()
