"""Loading image batches (files, folders, zip archives) and writing results."""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

import cv2
import numpy as np

from .detectors import METHODS, detect

log = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
# ALZip's own formats; Python can't read them, the user has to re-save as zip.
UNSUPPORTED_ARCHIVES = {".alz", ".egg", ".rar", ".7z"}


@dataclass
class Item:
    name: str                      # relative path used for the output, "/"-separated
    image: np.ndarray              # BGR uint8
    alpha: np.ndarray | None = None

    @property
    def ext(self) -> str:
        return PurePosixPath(self.name).suffix.lower() or ".png"


def decode_image(data: bytes) -> tuple[np.ndarray, np.ndarray | None] | None:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.dtype != np.uint8:
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), None
    if img.shape[2] == 4:
        return img[..., :3].copy(), img[..., 3].copy()
    return img, None


def encode_image(item: Item, image: np.ndarray) -> bytes:
    ext = item.ext
    if item.alpha is not None and ext in (".png", ".webp", ".tif", ".tiff"):
        image = np.dstack([image, item.alpha])
    params = [cv2.IMWRITE_JPEG_QUALITY, 95] if ext in (".jpg", ".jpeg") else []
    ok, buf = cv2.imencode(ext, image, params)
    if not ok:
        raise OSError(f"cannot encode {item.name}")
    return buf.tobytes()


def _zip_name(info: zipfile.ZipInfo) -> str:
    """Archive member name, fixing Korean names from Windows archivers.

    Zip files made by Windows tools (ALZip, Explorer, Bandizip in legacy
    mode) store names in CP949 without setting the UTF-8 flag, and Python
    then decodes them as CP437, producing garbage.
    """
    name = info.filename
    if not info.flag_bits & 0x800:
        raw = name.encode("cp437", errors="replace")
        for enc in ("utf-8", "cp949"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                pass
    return name


def _from_zip(data: bytes, prefix: str, items: list[Item], errors: list[str]) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = _zip_name(info)
            parts = PurePosixPath(name.replace("\\", "/")).parts
            if not parts or parts[0] == "__MACOSX" or parts[-1].startswith("._"):
                continue
            rel = "/".join(p for p in parts if p not in ("..", "/"))
            if PurePosixPath(rel).suffix.lower() not in IMAGE_EXTS:
                continue
            try:
                blob = zf.read(info)
            except RuntimeError:  # encrypted member
                errors.append(f"{rel}: 암호가 걸린 파일이라 열 수 없습니다")
                continue
            _add(blob, f"{prefix}/{rel}" if prefix else rel, items, errors)


def _add(data: bytes, name: str, items: list[Item], errors: list[str]) -> None:
    decoded = decode_image(data)
    if decoded is None:
        errors.append(f"{name}: 이미지를 읽을 수 없습니다")
        return
    items.append(Item(name, *decoded))


def load(paths: list[str | Path]) -> tuple[list[Item], list[str]]:
    """Read images from files, folders and zip archives.

    Returns the images and human-readable (Korean) messages for anything
    that was skipped. Names inside a zip keep their folder structure.
    """
    items: list[Item] = []
    errors: list[str] = []
    for p in map(Path, paths):
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and (f.suffix.lower() in IMAGE_EXTS or f.suffix.lower() == ".zip"):
                    _load_file(f, f.relative_to(p).parent.as_posix(), items, errors)
        elif p.is_file():
            _load_file(p, "", items, errors)
        else:
            errors.append(f"{p}: 파일이 없습니다")
    # Output names must be unique (two uploads may share a file name).
    seen: dict[str, int] = {}
    for it in items:
        key = it.name.lower()
        if key in seen:
            seen[key] += 1
            stem, ext = it.name.rsplit(".", 1) if "." in it.name else (it.name, "png")
            it.name = f"{stem}_{seen[key]}.{ext}"
        else:
            seen[key] = 1
    return items, errors


def _load_file(f: Path, folder: str, items: list[Item], errors: list[str]) -> None:
    ext = f.suffix.lower()
    prefix = "" if folder in ("", ".") else folder
    if ext in UNSUPPORTED_ARCHIVES:
        errors.append(f"{f.name}: {ext} 형식은 지원하지 않습니다. "
                      "알집에서 '.zip' 형식으로 다시 압축해 주세요")
        return
    data = f.read_bytes()
    if ext == ".zip" or zipfile.is_zipfile(io.BytesIO(data)) and ext not in IMAGE_EXTS:
        try:
            _from_zip(data, prefix, items, errors)
        except zipfile.BadZipFile:
            errors.append(f"{f.name}: 손상된 zip 파일입니다")
        return
    if ext not in IMAGE_EXTS:
        errors.append(f"{f.name}: 이미지 파일이 아닙니다")
        return
    _add(data, f"{prefix}/{f.name}" if prefix else f.name, items, errors)


def process(items: list[Item], inpainter, methods: tuple[str, ...] = METHODS,
            sensitivity: float = 0.5,
            progress: Callable[[int, int, str], None] | None = None
            ) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Detect and remove watermarks. Returns (results, masks) in item order."""
    if progress:
        progress(0, len(items), "워터마크 찾는 중")
    masks = detect([it.image for it in items], methods, sensitivity)
    results = []
    for k, (it, m) in enumerate(zip(items, masks)):
        if progress:
            progress(k, len(items), f"지우는 중: {it.name}")
        results.append(inpainter(it.image, m) if m.any() else it.image.copy())
    if progress:
        progress(len(items), len(items), "완료")
    return results, masks


def write_zip(path: str | Path, items: list[Item], results: list[np.ndarray],
              masks: list[np.ndarray] | None = None) -> Path:
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for k, (it, res) in enumerate(zip(items, results)):
            zf.writestr(it.name, encode_image(it, res))
            if masks is not None and masks[k].any():
                stem = it.name.rsplit(".", 1)[0]
                ok, buf = cv2.imencode(".png", masks[k])
                zf.writestr(f"_masks/{stem}_mask.png", buf.tobytes())
    return path


def write_dir(out_dir: str | Path, items: list[Item], results: list[np.ndarray],
              masks: list[np.ndarray] | None = None) -> list[Path]:
    out_dir = Path(out_dir)
    written = []
    for k, (it, res) in enumerate(zip(items, results)):
        dest = out_dir / it.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(encode_image(it, res))
        written.append(dest)
        if masks is not None:
            mdest = dest.with_name(f"{dest.stem}_mask.png")
            mdest.write_bytes(cv2.imencode(".png", masks[k])[1].tobytes())
    return written
