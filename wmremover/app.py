"""Local web UI: drop images or zip archives, download the cleaned zip."""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

from . import batch
from .inpainters import get_inpainter

log = logging.getLogger(__name__)

PREVIEW_LIMIT = 24
PREVIEW_SIDE = 900

_inpainter = None


def _get_inpainter():
    global _inpainter
    if _inpainter is None:
        _inpainter = get_inpainter("auto")
    return _inpainter


def _preview(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    s = min(1.0, PREVIEW_SIDE / max(h, w))
    if s < 1:
        image = cv2.resize(image, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def run(files, find_text: bool, faint: bool, progress=None):
    """Gradio callback. Returns (gallery, zip path, report markdown)."""
    if not files:
        return [], None, "사진이나 zip 파일을 먼저 올려 주세요."
    paths = [f if isinstance(f, str) else f.name for f in files]
    items, errors = batch.load(paths)
    if not items:
        return [], None, "읽을 수 있는 이미지가 없습니다.\n\n" + "\n".join(f"- {e}" for e in errors)

    methods = ("consensus", "text") if find_text else ("consensus",)
    sensitivity = 0.8 if faint else 0.5
    start = time.time()

    def report(done, total, msg):
        if progress is not None:
            progress(done / max(total, 1), desc=f"{msg} ({done}/{total})")

    if progress is not None:
        progress(0, desc="AI 모델 준비 중 (처음 한 번은 몇 분 걸릴 수 있습니다)")
    inpainter = _get_inpainter()
    results, masks = batch.process(items, inpainter, methods, sensitivity, report)

    out_dir = Path(tempfile.mkdtemp(prefix="wmremover_"))
    zip_path = batch.write_zip(out_dir / "워터마크_제거결과.zip", items, results)

    gallery = []
    for it, res, m in list(zip(items, results, masks))[:PREVIEW_LIMIT]:
        if m.any():
            gallery.append((_preview(it.image), f"전: {it.name}"))
            gallery.append((_preview(res), f"후: {it.name}"))

    found = sum(bool(m.any()) for m in masks)
    lines = [
        f"**{len(items)}장 처리 완료** ({time.time() - start:.0f}초)",
        f"- 워터마크를 찾아서 지운 사진: {found}장",
        f"- 워터마크를 못 찾은 사진 (그대로 저장): {len(items) - found}장",
    ]
    if inpainter.name != "lama":
        lines.append("- 참고: AI 복원 모델을 불러오지 못해 기본 복원 방식을 사용했습니다")
    if found and len(items) > PREVIEW_LIMIT:
        lines.append(f"- 미리보기는 앞의 {PREVIEW_LIMIT}장만 보여 줍니다. 전체는 zip 파일에 있습니다")
    if errors:
        lines.append("\n**건너뛴 파일**")
        lines += [f"- {e}" for e in errors]
    return gallery, str(zip_path), "\n".join(lines)


def build():
    import gradio as gr

    with gr.Blocks(title="워터마크 제거기") as demo:
        gr.Markdown(
            "# 워터마크 제거기\n"
            "사진 파일이나 **zip 압축파일**을 아래에 끌어다 놓고 **워터마크 지우기**를 누르세요. "
            "결과는 zip 파일로 받을 수 있습니다.\n\n"
            "같은 워터마크가 찍힌 **같은 크기의 사진이 5장 이상**이면 글자·로고 모두 잘 지워집니다. "
            "한 장만 있으면 **글자로 된 워터마크만** 찾습니다."
        )
        files = gr.File(label="사진 또는 zip 파일 (여러 개 가능)", file_count="multiple",
                        file_types=[".zip", "image"])
        with gr.Row():
            find_text = gr.Checkbox(
                True, label="글자 워터마크 찾기",
                info="사진 속 원래 글자(간판, 옷 글씨 등)도 지워질 수 있습니다. 그런 사진이면 끄세요.")
            faint = gr.Checkbox(
                False, label="옅은 워터마크도 찾기",
                info="더 꼼꼼히 찾지만 느려지고, 엉뚱한 곳을 지울 가능성이 커집니다.")
        go = gr.Button("워터마크 지우기", variant="primary")
        report = gr.Markdown()
        result = gr.File(label="결과 다운로드")
        gallery = gr.Gallery(label="미리보기 (전 / 후)", columns=2, height="auto")

        def _run(f, t, fa, progress=gr.Progress()):
            return run(f, t, fa, progress)

        go.click(_run, [files, find_text, faint], [gallery, result, report])
    return demo


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    print("워터마크 제거기를 시작합니다. 브라우저가 자동으로 열립니다.")
    print("이 창을 닫으면 프로그램이 종료됩니다.")
    build().queue().launch(inbrowser=True, server_name="127.0.0.1")


if __name__ == "__main__":
    main()
