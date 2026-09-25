"""Command line interface: ``wmremover IMAGE... -o OUTDIR``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

from .detectors import METHODS, detect
from .inpainters import get_inpainter

EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _collect(paths: list[str]) -> list[Path]:
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in EXTS)
        else:
            files.append(p)
    return files


def _read(path: Path) -> np.ndarray | None:
    # imdecode handles non-ASCII paths, which cv2.imread does not on Windows.
    data = np.fromfile(str(path), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return img


def _write(path: Path, img: np.ndarray) -> None:
    ok, buf = cv2.imencode(path.suffix or ".png", img)
    if not ok:
        raise OSError(f"cannot encode {path}")
    buf.tofile(str(path))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="wmremover",
        description="Detect watermarks automatically and inpaint them away.")
    ap.add_argument("inputs", nargs="+", help="image files or directories")
    ap.add_argument("-o", "--output", default="output", help="output directory (default: output)")
    ap.add_argument("-m", "--methods", default=",".join(METHODS),
                    help=f"comma-separated detectors from {', '.join(METHODS)} (default: all)")
    ap.add_argument("-s", "--sensitivity", type=float, default=0.5,
                    help="0..1, higher finds fainter marks but more false positives (default: 0.5)")
    ap.add_argument("-i", "--inpainter", choices=("auto", "lama", "opencv"), default="auto",
                    help="auto = LaMa if available, else OpenCV")
    ap.add_argument("--mask", help="use this mask image (white = remove) instead of detecting")
    ap.add_argument("--save-mask", action="store_true", help="also write <name>_mask.png")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    methods = tuple(m.strip() for m in args.methods.split(",") if m.strip())
    unknown = set(methods) - set(METHODS)
    if unknown:
        ap.error(f"unknown detector(s): {', '.join(sorted(unknown))}")

    files = _collect(args.inputs)
    images, names = [], []
    for f in files:
        img = _read(f) if f.exists() else None
        if img is None:
            print(f"skip: cannot read {f}", file=sys.stderr)
            continue
        images.append(img)
        names.append(f)
    if not images:
        print("no readable images", file=sys.stderr)
        return 1

    if args.mask:
        m = _read(Path(args.mask))
        if m is None:
            ap.error(f"cannot read mask {args.mask}")
        m = cv2.cvtColor(m, cv2.COLOR_BGR2GRAY)
        masks = [cv2.resize(m, img.shape[1::-1], interpolation=cv2.INTER_NEAREST) > 127
                 for img in images]
        masks = [mk.astype(np.uint8) * 255 for mk in masks]
    else:
        masks = detect(images, methods, args.sensitivity)

    inpaint = get_inpainter(args.inpainter)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    for img, mask, name in zip(images, masks, names):
        coverage = 100 * float(mask.mean()) / 255
        result = inpaint(img, mask) if mask.any() else img
        _write(out_dir / name.name, result)
        if args.save_mask:
            _write(out_dir / f"{name.stem}_mask.png", mask)
        status = f"{coverage:.2f}% masked" if mask.any() else "no watermark found"
        print(f"{name} -> {out_dir / name.name} ({status}, {inpaint.name})")
    return 0
