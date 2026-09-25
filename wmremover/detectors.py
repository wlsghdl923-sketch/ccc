"""Automatic watermark detection.

Two detectors, combined by :func:`detect`:

* ``consensus`` - several same-sized images sharing one watermark (a batch
  from the same site/camera/export). Gradients that agree in sign across the
  images belong to the watermark, scene content doesn't agree; integrating
  the agreeing gradient field recovers the mark's shape. After Dekel et al.,
  "On the Effectiveness of Visible Watermarks" (CVPR 2017). Finds text *and*
  logos and is by far the more precise detector.
* ``text`` - CRAFT text detector (via EasyOCR) on the image and on a
  contrast-boosted copy, so faint semi-transparent text is found as well.
  Works on a single image, but it cannot tell watermark text from text that
  belongs to the picture, and it does not find non-text logos.

Every detector returns a uint8 mask (255 = watermark) the size of the image.
"""

from __future__ import annotations

import logging
from collections import defaultdict

import cv2
import numpy as np

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- helpers

def _odd(n: float) -> int:
    n = max(3, int(round(n)))
    return n if n % 2 else n + 1


def _ellipse(size: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def _remove_small(mask: np.ndarray, min_area: int) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return np.where(keep[labels], 255, 0).astype(np.uint8)


# ---------------------------------------------------------------- consensus

_FILL_FRAC = 0.3
_CLOSE = 3
_WEAK = 0.45


def detect_consensus(images: list[np.ndarray], min_images: int = 3) -> list[np.ndarray | None]:
    """Masks for images that share a watermark with >= ``min_images - 1`` others.

    Images are grouped by exact size (a shared watermark is only aligned when
    the images have the same dimensions). Returns ``None`` for images that
    couldn't be grouped.
    """
    groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, img in enumerate(images):
        groups[img.shape[:2]].append(i)

    masks: list[np.ndarray | None] = [None] * len(images)
    for (h, w), idx in groups.items():
        if len(idx) < min_images:
            continue
        gx, gy = [], []
        for i in idx:
            g = cv2.cvtColor(images[i], cv2.COLOR_BGR2GRAY).astype(np.float32)
            gx.append(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3))
            gy.append(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
        # A watermark edge has the same gradient sign in (almost) every image,
        # a scene edge doesn't. Take a low quantile of the gradient in each
        # direction: it is large only where nearly all images agree. One in
        # five images may disagree (e.g. a white mark over a white sky).
        n = len(idx)
        q = int(0.2 * n) / (n - 1)
        gx, gy = np.stack(gx), np.stack(gy)
        ax, ay = _agreeing(gx, q), _agreeing(gy, q)
        # Majority vote (median) for the weak edges below: a mark over a
        # bright area is faint in many images, so the strict quantile misses it.
        mx, my = np.median(gx, axis=0), np.median(gy, axis=0)
        del gx, gy
        mag = np.hypot(ax, ay)

        # Scene gradients almost never agree across images, so the agreeing
        # magnitude is ~0 off the watermark; its bulk gives the noise floor.
        thr = max(24.0, 4.0 * float(np.percentile(mag, 95)))
        edges = _remove_small((mag > thr).astype(np.uint8) * 255, max(4, (h * w) // 100_000))
        if edges.any():
            # Hysteresis, as in Canny: weaker edges near the strong ones count
            # when they connect to them. Recovers strokes where several
            # images show the mark only faintly.
            near = cv2.dilate(edges, _ellipse(_odd(max(h, w) / 40))) > 0
            weak = ((mag > _WEAK * thr) | (np.hypot(mx, my) > thr)) & near
            edges = _hysteresis(edges, weak.astype(np.uint8) * 255)
            # Where the median is what found an edge, use it for the shape too.
            use_med = (edges > 0) & (np.abs(ax) + np.abs(ay) < np.abs(mx) + np.abs(my))
            ax, ay = np.where(use_med, mx, ax), np.where(use_med, my, ay)
        if not edges.any():
            log.info("consensus: no shared watermark in %d images of %dx%d", len(idx), w, h)
            continue
        # Edges only outline the strokes. Integrate the shared gradient field
        # (restricted to those edges) to recover the watermark's shape, which
        # fills the stroke interiors, then threshold it.
        keep = cv2.dilate(edges, _ellipse(3)) > 0
        shape = np.abs(_poisson(np.where(keep, ax, 0) / 8, np.where(keep, ay, 0) / 8))
        shape -= np.median(shape)
        t = max(2.0, _FILL_FRAC * float(np.percentile(shape[edges > 0], 90)))
        mask = ((shape > t) | (edges > 0)).astype(np.uint8) * 255
        mask = _remove_small(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _ellipse(_CLOSE)),
                             max(4, (h * w) // 100_000))
        mask = cv2.dilate(mask, _ellipse(5))
        for i in idx:
            masks[i] = mask.copy()
    return masks


def _hysteresis(strong: np.ndarray, weak: np.ndarray) -> np.ndarray:
    """Components of ``weak`` that contain at least one ``strong`` pixel."""
    n, labels = cv2.connectedComponents(weak | strong, connectivity=8)
    keep = np.zeros(n, bool)
    keep[np.unique(labels[strong > 0])] = True
    keep[0] = False
    return np.where(keep[labels], 255, 0).astype(np.uint8)


def _agreeing(g: np.ndarray, q: float) -> np.ndarray:
    """Signed gradient component that ~all images share, 0 where they disagree."""
    lo, hi = np.quantile(g, [q, 1 - q], axis=0)
    return np.where(lo > 0, lo, np.where(hi < 0, hi, 0)).astype(np.float32)


def _poisson(gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    """Least-squares integration of a gradient field (DCT, Neumann boundary)."""
    h, w = gx.shape
    div = cv2.Sobel(gx, cv2.CV_32F, 1, 0, ksize=3) / 8 + cv2.Sobel(gy, cv2.CV_32F, 0, 1, ksize=3) / 8
    # cv2.dct needs even dimensions.
    div = np.pad(div, ((0, h % 2), (0, w % 2)), mode="edge")
    H, W = div.shape
    f = cv2.dct(div)
    yy = 2 * np.cos(np.pi * np.arange(H) / H) - 2
    xx = 2 * np.cos(np.pi * np.arange(W) / W) - 2
    denom = (yy[:, None] + xx[None, :]).astype(np.float32)
    denom[0, 0] = 1
    f /= denom
    f[0, 0] = 0
    return cv2.idct(f)[:h, :w]


# ---------------------------------------------------------------- text (CRAFT)

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr  # heavy import; only when the text detector is used

        _reader = easyocr.Reader(["en"], gpu=False, recognizer=False, verbose=False)
    return _reader


def _text_variants(image: np.ndarray, names) -> list[np.ndarray]:
    h, w = image.shape[:2]
    L = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)[..., 0]
    gray = lambda g: cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)  # noqa: E731
    k = _ellipse(_odd(max(h, w) / 25))
    make = {
        "orig": lambda: image,
        "clahe": lambda: gray(cv2.createCLAHE(4.0, (8, 8)).apply(L)),
        # Top-hat/black-hat pull faint thin strokes out of the background.
        "tophat": lambda: gray(cv2.normalize(cv2.morphologyEx(L, cv2.MORPH_TOPHAT, k),
                                             None, 0, 255, cv2.NORM_MINMAX)),
        "blackhat": lambda: gray(cv2.normalize(cv2.morphologyEx(L, cv2.MORPH_BLACKHAT, k),
                                               None, 0, 255, cv2.NORM_MINMAX)),
    }
    return [make[n]() for n in names]


TEXT_VARIANTS = ("orig", "clahe")
# Morphological variants add a little recall on faint marks at 2x the cost.
TEXT_VARIANTS_SENSITIVE = ("orig", "clahe", "tophat", "blackhat")


def text_regions(image: np.ndarray, sensitivity: float = 0.5,
                 variants: tuple[str, ...] | None = None) -> list[np.ndarray]:
    """One filled mask per text region CRAFT finds on the image or its variants."""
    if variants is None:
        variants = TEXT_VARIANTS_SENSITIVE if sensitivity > 0.7 else TEXT_VARIANTS
    reader = _get_reader()
    h, w = image.shape[:2]
    regions = []
    for v in _text_variants(image, variants):
        horizontal, free = reader.detect(
            cv2.cvtColor(v, cv2.COLOR_BGR2RGB),
            text_threshold=0.85 - 0.4 * sensitivity, low_text=0.5 - 0.2 * sensitivity,
            link_threshold=0.4, canvas_size=2560,
            mag_ratio=float(np.clip(960 / max(h, w), 1.0, 2.0)),
            width_ths=0.7, add_margin=0.05,
        )
        polys = [np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
                 for x0, x1, y0, y1 in horizontal[0]]
        polys += [np.array(p) for p in free[0]]
        for pts in polys:
            r = np.zeros((h, w), np.uint8)
            cv2.fillPoly(r, [np.round(pts).astype(np.int32)], 255)
            _, _, bw, bh = cv2.boundingRect(np.round(pts).astype(np.int32))
            # CRAFT boxes hug the glyphs; grow them so stroke ends are included.
            regions.append(cv2.dilate(r, _ellipse(_odd(0.3 * min(bw, bh)))))
    return regions


def detect_text(image: np.ndarray, sensitivity: float = 0.5,
                variants: tuple[str, ...] | None = None) -> np.ndarray:
    """Mask of text found by CRAFT on the image and enhanced copies of it.

    Whole (slightly grown) text boxes are masked rather than individual
    strokes: stroke segmentation of semi-transparent text proved unreliable,
    and LaMa fills box-shaped holes cleanly.
    """
    mask = np.zeros(image.shape[:2], np.uint8)
    for r in text_regions(image, sensitivity, variants):
        mask |= r
    return mask


# ---------------------------------------------------------------- combined

METHODS = ("consensus", "text")


def detect(images: list[np.ndarray], methods: tuple[str, ...] = METHODS,
           sensitivity: float = 0.5) -> list[np.ndarray]:
    """Run the selected detectors and return one mask per image.

    When the consensus detector finds a shared watermark for an image, the
    text detector is skipped for it: consensus is far more precise and text
    detection would only add false positives (text that is part of the scene).
    """
    masks = [np.zeros(img.shape[:2], np.uint8) for img in images]
    done = [False] * len(images)
    if "consensus" in methods:
        for i, m in enumerate(detect_consensus(images)):
            if m is not None:
                masks[i] = m
                done[i] = True

    if "text" in methods and not all(done):
        try:
            _get_reader()
        except Exception as exc:  # not installed, or torch fails to load its DLLs
            log.warning("text detector unavailable (%s); only batch detection is used", exc)
            return masks
        for i, img in enumerate(images):
            if not done[i]:
                masks[i] = detect_text(img, sensitivity)
    return masks
