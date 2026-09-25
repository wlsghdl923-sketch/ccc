import zipfile

import cv2
import numpy as np

from wmremover import batch


def _png(img):
    return cv2.imencode(".png", img)[1].tobytes()


def _legacy_zip(path, members):
    """Zip with CP949 names and no UTF-8 flag, as ALZip/Explorer write them."""
    orig = zipfile.ZipInfo._encodeFilenameFlags
    zipfile.ZipInfo._encodeFilenameFlags = lambda self: (self.filename.encode("cp949"), self.flag_bits)
    try:
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)
    finally:
        zipfile.ZipInfo._encodeFilenameFlags = orig


def test_zip_with_korean_names_and_folders(tmp_path):
    img = np.full((20, 30, 3), 128, np.uint8)
    _legacy_zip(tmp_path / "사진.zip", {
        "여행/바다.png": _png(img),
        "산.png": _png(img),
        "메모.txt": b"hello",
        "__MACOSX/._산.png": b"junk",
    })
    items, errors = batch.load([tmp_path / "사진.zip"])
    assert sorted(i.name for i in items) == ["산.png", "여행/바다.png"]
    assert errors == []


def test_alpha_channel_survives_round_trip(tmp_path):
    rgba = np.zeros((10, 10, 4), np.uint8)
    rgba[..., 3] = 77
    (tmp_path / "a.png").write_bytes(_png(rgba))
    items, _ = batch.load([tmp_path / "a.png"])
    out = cv2.imdecode(np.frombuffer(batch.encode_image(items[0], items[0].image), np.uint8),
                       cv2.IMREAD_UNCHANGED)
    assert out.shape == (10, 10, 4) and (out[..., 3] == 77).all()


def test_alz_gets_a_helpful_message(tmp_path):
    (tmp_path / "x.alz").write_bytes(b"ALZ\x01")
    items, errors = batch.load([tmp_path / "x.alz"])
    assert items == [] and ".zip" in errors[0]


def test_duplicate_names_are_made_unique(tmp_path):
    img = _png(np.zeros((5, 5, 3), np.uint8))
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "p.png").write_bytes(img)
    items, _ = batch.load([tmp_path / "a" / "p.png", tmp_path / "b" / "p.png"])
    assert [i.name for i in items] == ["p.png", "p_2.png"]


def test_write_zip_keeps_structure(tmp_path):
    img = np.zeros((5, 5, 3), np.uint8)
    items = [batch.Item("폴더/사진.jpg", img)]
    batch.write_zip(tmp_path / "out.zip", items, [img])
    with zipfile.ZipFile(tmp_path / "out.zip") as zf:
        assert zf.namelist() == ["폴더/사진.jpg"]
