"""Automatic watermark detection and removal for images."""

from .detectors import METHODS, detect
from .inpainters import get_inpainter

__all__ = ["METHODS", "detect", "get_inpainter", "remove_watermarks"]


def remove_watermarks(images, methods=METHODS, sensitivity=0.5, inpainter="auto"):
    """Detect and inpaint watermarks in BGR uint8 images.

    Returns a list of ``(result, mask)`` pairs, one per input image.
    """
    fill = get_inpainter(inpainter) if isinstance(inpainter, str) else inpainter
    masks = detect(images, methods, sensitivity)
    return [(fill(img, m) if m.any() else img.copy(), m) for img, m in zip(images, masks)]
