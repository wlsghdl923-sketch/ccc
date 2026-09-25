"""Synthetic watermarks with known ground truth, for tests and evaluation."""

from __future__ import annotations

import glob

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    names = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"]
    for n in names:
        hits = glob.glob(f"/usr/share/fonts/**/{n}", recursive=True)
        if hits:
            return ImageFont.truetype(hits[0], size)
    return ImageFont.load_default()


def text_alpha(shape, text, size, pos="center", angle=0.0) -> np.ndarray:
    """Float coverage map (0..1) of rendered text."""
    h, w = shape[:2]
    layer = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(layer)
    font = _font(size)
    x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
    tw, th = x1 - x0, y1 - y0
    if pos == "center":
        xy = ((w - tw) // 2 - x0, (h - th) // 2 - y0)
    elif pos == "bottom-right":
        m = max(8, w // 40)
        xy = (w - tw - m - x0, h - th - m - y0)
    else:
        xy = pos
    draw.text(xy, text, fill=255, font=font)
    if angle:
        layer = layer.rotate(angle, resample=Image.BICUBIC, center=(w / 2, h / 2))
    return np.asarray(layer, np.float32) / 255


def logo_alpha(shape, radius, center=None) -> np.ndarray:
    h, w = shape[:2]
    cx, cy = center or (w // 2, h // 2)
    a = np.zeros((h, w), np.float32)
    t = max(3, radius // 6)
    cv2.circle(a, (cx, cy), radius, 1.0, t, cv2.LINE_AA)
    pts = np.array([[cx - radius // 2, cy + radius // 3], [cx, cy - radius // 2],
                    [cx + radius // 2, cy + radius // 3]], np.int32)
    cv2.polylines(a, [pts], True, 1.0, t, cv2.LINE_AA)
    return a


def apply(image: np.ndarray, coverage: np.ndarray, opacity: float, color=(255, 255, 255)):
    """Blend a watermark. Returns (watermarked image, ground-truth uint8 mask)."""
    a = (coverage * opacity)[..., None]
    out = image.astype(np.float32) * (1 - a) + np.array(color, np.float32) * a
    gt = (coverage > 0.05).astype(np.uint8) * 255
    return np.clip(out + 0.5, 0, 255).astype(np.uint8), gt


def score(mask: np.ndarray, gt: np.ndarray) -> tuple[float, float]:
    """(recall, precision) with a small tolerance band around the ground truth."""
    m = mask > 0
    g = gt > 0
    g_tol = cv2.dilate(gt, np.ones((9, 9), np.uint8)) > 0
    recall = (m & g).sum() / max(1, g.sum())
    precision = (m & g_tol).sum() / max(1, m.sum()) if m.any() else 1.0
    return float(recall), float(precision)


def psnr(a: np.ndarray, b: np.ndarray, region: np.ndarray) -> float:
    sel = region > 0
    mse = np.mean((a[sel].astype(np.float32) - b[sel].astype(np.float32)) ** 2)
    return float(10 * np.log10(255 ** 2 / max(mse, 1e-6)))
