"""Command line interface: ``wmremover INPUT... -o OUTPUT``.

Inputs may be image files, folders or zip archives. The output is a folder,
or a zip archive when OUTPUT ends in ``.zip``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

from . import batch
from .detectors import METHODS
from .inpainters import get_inpainter


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="wmremover",
        description="Detect watermarks automatically and inpaint them away.")
    ap.add_argument("inputs", nargs="+", help="image files, folders or .zip archives")
    ap.add_argument("-o", "--output", default="output",
                    help="output folder, or a .zip file (default: output)")
    ap.add_argument("-m", "--methods", default=",".join(METHODS),
                    help=f"comma-separated detectors from {', '.join(METHODS)} (default: all)")
    ap.add_argument("-s", "--sensitivity", type=float, default=0.5,
                    help="0..1, higher finds fainter marks but more false positives (default: 0.5)")
    ap.add_argument("-i", "--inpainter", choices=("auto", "lama", "opencv"), default="auto",
                    help="auto = LaMa if available, else OpenCV")
    ap.add_argument("--mask", help="use this mask image (white = remove) instead of detecting")
    ap.add_argument("--save-mask", action="store_true", help="also write the detected masks")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    methods = tuple(m.strip() for m in args.methods.split(",") if m.strip())
    unknown = set(methods) - set(METHODS)
    if unknown:
        ap.error(f"unknown detector(s): {', '.join(sorted(unknown))}")

    items, errors = batch.load(args.inputs)
    for e in errors:
        print(f"skip: {e}", file=sys.stderr)
    if not items:
        print("no readable images", file=sys.stderr)
        return 1

    inpaint = get_inpainter(args.inpainter)
    if args.mask:
        decoded = batch.decode_image(Path(args.mask).read_bytes())
        if decoded is None:
            ap.error(f"cannot read mask {args.mask}")
        gray = cv2.cvtColor(decoded[0], cv2.COLOR_BGR2GRAY)
        masks = [(cv2.resize(gray, it.image.shape[1::-1], interpolation=cv2.INTER_NEAREST) > 127)
                 .astype(np.uint8) * 255 for it in items]
        results = [inpaint(it.image, m) for it, m in zip(items, masks)]
    else:
        results, masks = batch.process(items, inpaint, methods, args.sensitivity)

    saved_masks = masks if args.save_mask else None
    if args.output.lower().endswith(".zip"):
        batch.write_zip(args.output, items, results, saved_masks)
    else:
        batch.write_dir(args.output, items, results, saved_masks)
    for it, m in zip(items, masks):
        status = f"{100 * float(m.mean()) / 255:.2f}% masked" if m.any() else "no watermark found"
        print(f"{it.name}: {status}")
    print(f"-> {args.output} ({inpaint.name})")
    return 0
