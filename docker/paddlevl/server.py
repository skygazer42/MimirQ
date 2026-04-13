from __future__ import annotations

import io
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

app = FastAPI(title="mimirq-paddlevl", version="0.2.0")


def _make_zip(root: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(root)))
    return buffer.getvalue()


def _run_doc_parser(
    *,
    pdf_path: Path,
    out_dir: Path,
    pipeline_version: str,
    device: str,
) -> None:
    """
    Run PaddleOCR doc_parser (PaddleOCR-VL pipeline) to produce Markdown/JSON/images outputs.

    Docs: https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html#paddleocr-vl-document-level-parsing-pipeline
    """
    cmd = [
        "paddleocr",
        "doc_parser",
        "-i",
        str(pdf_path),
        "--save_path",
        str(out_dir),
        "--pipeline_version",
        str(pipeline_version or "v1.5"),
        "--device",
        str(device or "cpu"),
    ]

    env = os.environ.copy()
    # Keep logs readable and avoid broken unicode in some terminals.
    env.setdefault("PYTHONIOENCODING", "utf-8")

    proc = subprocess.run(  # noqa: S603
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        out = (proc.stdout or "").strip()
        raise RuntimeError(f"doc_parser failed (exit={proc.returncode}): {out[-2000:]}")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "doc_parser",
        "pipeline_version": (os.environ.get("PADDLEOCR_PIPELINE_VERSION") or "v1.5").strip() or "v1.5",
        "device": (os.environ.get("PADDLEOCR_DEVICE") or "cpu").strip() or "cpu",
    }


@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    output_format: str = Form("markdown"),  # kept for parity; ignored (always ZIP)
    dpi: int = Form(150),  # kept for parity; ignored by doc_parser
    pipeline_version: str = Form(""),
    device: str = Form(""),
) -> Response:
    name = (file.filename or "").lower()
    if not name.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF is supported")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    pipeline_version = (pipeline_version or os.environ.get("PADDLEOCR_PIPELINE_VERSION") or "v1.5").strip() or "v1.5"
    device = (device or os.environ.get("PADDLEOCR_DEVICE") or "cpu").strip() or "cpu"

    with tempfile.TemporaryDirectory(prefix="mimirq_paddlevl_") as tmp:
        tmp_path = Path(tmp)
        pdf_path = tmp_path / "input.pdf"
        pdf_path.write_bytes(pdf_bytes)

        output_root = tmp_path / "output"
        output_root.mkdir(parents=True, exist_ok=True)

        try:
            _run_doc_parser(pdf_path=pdf_path, out_dir=output_root, pipeline_version=pipeline_version, device=device)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)[:2000]) from exc

        return Response(content=_make_zip(output_root), media_type="application/zip")
