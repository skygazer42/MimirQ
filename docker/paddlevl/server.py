from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response


app = FastAPI(title="mimirq-paddlevl", version="0.1.0")

_OCR = None


def _get_ocr():
    global _OCR
    if _OCR is None:
        from paddleocr import PaddleOCR

        lang = (os.environ.get("PADDLEOCR_LANG") or "ch").strip() or "ch"
        _OCR = PaddleOCR(use_angle_cls=True, lang=lang)
    return _OCR


def _render_pdf_pages(pdf_path: Path, images_dir: Path, dpi: int) -> list[Path]:
    images_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    zoom = float(dpi) / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    out: list[Path] = []
    for page_index in range(int(doc.page_count)):
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        image_path = images_dir / f"page_{page_index + 1}.png"
        pix.save(str(image_path))
        out.append(image_path)

    doc.close()
    return out


def _ocr_page(image_path: Path) -> tuple[str, list[dict[str, Any]]]:
    ocr = _get_ocr()
    raw = ocr.ocr(str(image_path), cls=True)

    lines: list[dict[str, Any]] = []
    # paddleocr returns either a list of lines or a nested list per image
    candidates = raw
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], list):
        candidates = raw[0]

    for item in candidates or []:
        try:
            bbox, payload = item
            text, score = payload
        except Exception:
            continue

        if not text:
            continue

        xs = [p[0] for p in bbox] if isinstance(bbox, list) else []
        ys = [p[1] for p in bbox] if isinstance(bbox, list) else []
        block_bbox = []
        if xs and ys:
            block_bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]

        lines.append(
            {
                "block_label": "text",
                "block_bbox": block_bbox,
                "text": str(text),
                "score": float(score) if score is not None else None,
            }
        )

    def sort_key(block: dict[str, Any]) -> tuple[int, int]:
        bbox = block.get("block_bbox") or [0, 0, 0, 0]
        if isinstance(bbox, list) and len(bbox) == 4:
            return int(bbox[1]), int(bbox[0])
        return 0, 0

    lines.sort(key=sort_key)
    page_text = "\n".join([str(b.get("text") or "").strip() for b in lines if str(b.get("text") or "").strip()])
    return page_text, lines


def _make_zip(root: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(root)))
    return buffer.getvalue()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    output_format: str = Form("markdown"),  # kept for parity; ignored (always ZIP)
    dpi: int = Form(150),
) -> Response:
    name = (file.filename or "").lower()
    if not name.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF is supported")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    with tempfile.TemporaryDirectory(prefix="mimirq_paddlevl_") as tmp:
        tmp_path = Path(tmp)
        pdf_path = tmp_path / "input.pdf"
        pdf_path.write_bytes(pdf_bytes)

        output_root = tmp_path / "output"
        output_root.mkdir(parents=True, exist_ok=True)

        page_images_dir = tmp_path / "pages"
        page_images = _render_pdf_pages(pdf_path, page_images_dir, dpi=int(dpi or 150))

        md_parts: list[str] = []
        for idx, img_path in enumerate(page_images):
            page_dir = output_root / f"page_{idx + 1}"
            (page_dir / "imgs").mkdir(parents=True, exist_ok=True)

            page_text, blocks = _ocr_page(img_path)
            md_parts.append(f"## Page {idx + 1}\n\n{page_text}\n")

            page_json = {
                "page_index": idx,
                "parsing_res_list": blocks,
                "format": "paddleocr-vl-lite",
            }
            (page_dir / f"page_{idx + 1}_res.json").write_text(
                json.dumps(page_json, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        (output_root / "result.md").write_text("\n".join(md_parts).strip() + "\n", encoding="utf-8")

        return Response(content=_make_zip(output_root), media_type="application/zip")

