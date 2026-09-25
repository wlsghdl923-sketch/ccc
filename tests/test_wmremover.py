import cv2
import numpy as np
import pytest

from wmremover import cli
from wmremover.detectors import _poisson, detect, detect_consensus
from wmremover.inpainters import OpenCVInpainter, _region_crops

import synth


def _scenes(n, shape=(240, 320), seed=0):
    """Random smooth 'photos' with shapes, different per image."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        base = rng.integers(0, 256, (6, 8, 3)).astype(np.uint8)
        img = cv2.resize(base, shape[::-1], interpolation=cv2.INTER_CUBIC)
        for _ in range(6):
            c = tuple(int(v) for v in rng.integers(0, 256, 3))
            p = tuple(int(v) for v in rng.integers(0, min(shape), 2))
            cv2.circle(img, p, int(rng.integers(10, 60)), c, -1)
        img = cv2.add(img, rng.integers(0, 8, img.shape, dtype=np.uint8))
        out.append(img)
    return out


@pytest.mark.parametrize("color,opacity", [((255, 255, 255), 0.35), ((0, 0, 0), 0.4)])
def test_consensus_finds_shared_text(color, opacity):
    imgs = _scenes(6)
    cov = synth.text_alpha(imgs[0].shape, "SAMPLE", 60)
    marked, gts = zip(*[synth.apply(i, cov, opacity, color) for i in imgs])
    masks = detect_consensus(list(marked))
    for m, gt in zip(masks, gts):
        recall, precision = synth.score(m, gt)
        assert recall > 0.9 and precision > 0.8, (recall, precision)


def test_consensus_finds_logo():
    imgs = _scenes(5, seed=1)
    cov = synth.logo_alpha(imgs[0].shape, 50)
    marked, gts = zip(*[synth.apply(i, cov, 0.45) for i in imgs])
    recall, precision = synth.score(detect_consensus(list(marked))[0], gts[0])
    assert recall > 0.9 and precision > 0.8


def test_consensus_ignores_clean_images_and_small_groups():
    imgs = _scenes(6, seed=2)
    assert all(m is None for m in detect_consensus(imgs))
    assert detect_consensus(imgs[:2]) == [None, None]


def test_detect_skips_text_when_consensus_found():
    imgs = _scenes(4, seed=3)
    cov = synth.text_alpha(imgs[0].shape, "PREVIEW", 50)
    marked = [synth.apply(i, cov, 0.4)[0] for i in imgs]
    masks = detect(marked, methods=("consensus",))
    assert all(m.any() for m in masks)


def test_poisson_recovers_shape():
    f = np.zeros((64, 80), np.float32)
    f[20:40, 30:50] = 10
    gx = cv2.Sobel(f, cv2.CV_32F, 1, 0) / 8
    gy = cv2.Sobel(f, cv2.CV_32F, 0, 1) / 8
    rec = _poisson(gx, gy)
    rec -= np.median(rec)
    assert rec[25:35, 35:45].mean() > 7
    assert abs(rec[:10, :10].mean()) < 1


def test_region_crops_merge_overlapping():
    m = np.zeros((500, 500), np.uint8)
    m[100:110, 100:110] = 255
    m[100:110, 130:140] = 255
    m[400:410, 400:410] = 255
    crops = _region_crops(m, min_pad=20)
    assert len(crops) == 2


def test_opencv_inpainter_only_changes_mask():
    img = _scenes(1)[0]
    mask = np.zeros(img.shape[:2], np.uint8)
    mask[50:80, 50:120] = 255
    out = OpenCVInpainter()(img, mask)
    assert np.array_equal(out[mask == 0], img[mask == 0])


def test_cli_batch(tmp_path):
    imgs = _scenes(4, seed=4)
    cov = synth.text_alpha(imgs[0].shape, "DEMO", 70)
    src = tmp_path / "in"
    src.mkdir()
    for k, img in enumerate(imgs):
        cv2.imwrite(str(src / f"{k}.png"), synth.apply(img, cov, 0.4)[0])
    out = tmp_path / "out"
    assert cli.main([str(src), "-o", str(out), "-m", "consensus", "-i", "opencv", "--save-mask"]) == 0
    for k, img in enumerate(imgs):
        res = cv2.imread(str(out / f"{k}.png"))
        region = cov > 0.05
        before = np.abs(synth.apply(img, cov, 0.4)[0][region].astype(int) - img[region]).mean()
        after = np.abs(res[region].astype(int) - img[region]).mean()
        assert after < before * 0.6
        assert (out / f"{k}_mask.png").exists()


def test_cli_explicit_mask(tmp_path):
    img = _scenes(1)[0]
    cv2.imwrite(str(tmp_path / "a.png"), img)
    mask = np.zeros(img.shape[:2], np.uint8)
    mask[10:30, 10:60] = 255
    cv2.imwrite(str(tmp_path / "m.png"), mask)
    assert cli.main([str(tmp_path / "a.png"), "-o", str(tmp_path / "o"), "--mask",
                     str(tmp_path / "m.png"), "-i", "opencv"]) == 0
    assert (tmp_path / "o" / "a.png").exists()
