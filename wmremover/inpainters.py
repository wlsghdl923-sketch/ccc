"""Inpainting backends: LaMa (TorchScript) with an OpenCV fallback."""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

LAMA_URL = (
    "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/"
    "v0.1.0/big-lama.pt"
)
CACHE_DIR = Path(os.environ.get("WMREMOVER_CACHE", Path.home() / ".cache" / "wmremover"))


class OpenCVInpainter:
    """Classic diffusion-based inpainting. Fast, no model, blurry on texture."""

    name = "opencv"

    def __init__(self, radius: int = 5):
        self.radius = radius

    def __call__(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        return cv2.inpaint(image, mask, self.radius, cv2.INPAINT_TELEA)


class LamaInpainter:
    """LaMa (Suvorov et al., 2021) big-lama TorchScript model.

    Large images are processed as crops around each masked region so CPU
    inference stays tractable and the untouched pixels stay bit-exact.
    """

    name = "lama"

    def __init__(self, model_path: str | None = None, device: str | None = None,
                 max_side: int = 1024):
        import torch

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        path = Path(model_path) if model_path else _download(LAMA_URL, "big-lama.pt")
        self.model = torch.jit.load(str(path), map_location=self.device).eval()
        self.max_side = max_side

    def _run(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        torch = self.torch
        h, w = mask.shape
        scale = min(1.0, self.max_side / max(h, w))
        if scale < 1.0:
            size = (max(8, round(w * scale)), max(8, round(h * scale)))
            img_s = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
            msk_s = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
        else:
            img_s, msk_s = image, mask

        sh, sw = msk_s.shape
        ph, pw = (-sh) % 8, (-sw) % 8
        img_p = np.pad(img_s, ((0, ph), (0, pw), (0, 0)), mode="reflect")
        msk_p = np.pad(msk_s, ((0, ph), (0, pw)), mode="reflect")

        rgb = cv2.cvtColor(img_p, cv2.COLOR_BGR2RGB)
        t_img = torch.from_numpy(rgb).permute(2, 0, 1)[None].float().div(255).to(self.device)
        t_msk = torch.from_numpy((msk_p > 0).astype(np.float32))[None, None].to(self.device)
        with torch.inference_mode():
            out = self.model(t_img, t_msk)[0]
        out = out.permute(1, 2, 0).clamp(0, 1).mul(255).byte().cpu().numpy()[:sh, :sw]
        out = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
        if scale < 1.0:
            out = cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC)
        return out

    def __call__(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        result = image.copy()
        h, w = mask.shape
        for x0, y0, x1, y1 in _region_crops(mask):
            crop_img = image[y0:y1, x0:x1]
            crop_msk = mask[y0:y1, x0:x1]
            filled = self._run(crop_img, crop_msk)
            sel = crop_msk > 0
            result[y0:y1, x0:x1][sel] = filled[sel]
        return result


def _region_crops(mask: np.ndarray, context: float = 1.0, min_pad: int = 64):
    """Bounding boxes around mask blobs, grown by context and merged if they overlap."""
    h, w = mask.shape
    n, _, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    boxes = []
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        pad_x = max(min_pad, int(bw * context))
        pad_y = max(min_pad, int(bh * context))
        boxes.append([max(0, x - pad_x), max(0, y - pad_y),
                      min(w, x + bw + pad_x), min(h, y + bh + pad_y)])
    merged = True
    while merged:
        merged = False
        out = []
        for b in boxes:
            for o in out:
                if b[0] < o[2] and o[0] < b[2] and b[1] < o[3] and o[1] < b[3]:
                    o[:] = [min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3])]
                    merged = True
                    break
            else:
                out.append(b)
        boxes = out
    return [tuple(b) for b in boxes]


def _download(url: str, filename: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / filename
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    log.info("Downloading %s -> %s", url, dest)
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)
    return dest


def get_inpainter(name: str = "auto", **kwargs):
    if name == "opencv":
        return OpenCVInpainter()
    try:
        return LamaInpainter(**kwargs)
    except Exception as exc:  # torch missing, download failed, ...
        if name == "lama":
            raise
        log.warning("LaMa unavailable (%s); falling back to OpenCV inpainting", exc)
        return OpenCVInpainter()
