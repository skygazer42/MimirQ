import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Annotated

import torch
import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

app = FastAPI(title="mimirq-magicpdf", version="0.1.0")


def _get_bool_env(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _get_int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_MAX_CONCURRENT_JOBS = max(1, _get_int_env("MAGIC_PDF_MAX_CONCURRENT_JOBS", 1))
_MAX_UPLOAD_BYTES = max(1, _get_int_env("MAGIC_PDF_MAX_UPLOAD_BYTES", 50 * 1024 * 1024))
_PIPELINE_TIMEOUT_SEC = max(30, _get_int_env("MAGIC_PDF_PIPELINE_TIMEOUT_SEC", 600))
_ARTIFACT_ROOT = Path(os.environ.get("MAGIC_PDF_ARTIFACT_ROOT") or "/var/lib/mimirq/magicpdf-artifacts")
_CLI = (os.environ.get("MAGIC_PDF_CLI") or "magic-pdf").strip() or "magic-pdf"
_MODELS_DIR = (os.environ.get("MAGIC_PDF_MODELS_DIR") or "/opt/mimirq-model-cache").strip()
_DEFAULT_DEVICE_MODE = (os.environ.get("MAGIC_PDF_DEVICE_MODE") or "cuda").strip().lower() or "cuda"
_FORMULA_ENABLED = _get_bool_env("MAGIC_PDF_FORMULA_ENABLED", False)
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_JOBS)

_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\(\s*[^)\s]+?\s*\)\s*")
_IMAGE_HTML_RE = re.compile(r"<img[^>]*?>", flags=re.IGNORECASE)
_PDF_EXTRACT_KIT_MODEL_DIR = "models--opendatalab--PDF-Extract-Kit-1.0"
_REQUIRED_MODEL_FILES = (
    "Layout/YOLO/doclayout_yolo_docstructbench_imgsz1280_2501.pt",
    "OCR/paddleocr_torch/ch_PP-OCRv3_det_infer.pth",
    "OCR/paddleocr_torch/ch_PP-OCRv5_rec_infer.pth",
)
_CH_DOC_REC_MODEL = "ch_PP-OCRv4_rec_server_doc_infer.pth"
_CH_COMPAT_REC_MODEL = "ch_PP-OCRv5_rec_infer.pth"
_CH_COMPAT_DICT = "ppocrv5_dict.txt"


async def _read_upload(file: UploadFile) -> bytes:
    data = bytearray()
    while chunk := await file.read(min(1024 * 1024, _MAX_UPLOAD_BYTES + 1 - len(data))):
        data.extend(chunk)
        if len(data) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="upload too large")
    return bytes(data)


def _sanitize_run_id(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)[:120] or "magicpdf"
    return text


def _resolve_cli() -> str:
    resolved = shutil.which(_CLI)
    if resolved:
        return resolved
    raise RuntimeError(f"magic-pdf CLI not found: {_CLI}")


def _cuda_available() -> bool:
    try:
        if not bool(torch.cuda.is_available()):
            return False
    except (AttributeError, OSError, RuntimeError):
        return False

    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return True
    try:
        subprocess.run(
            [nvidia_smi, "-L"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _has_required_models(models_dir: Path) -> bool:
    try:
        return all((models_dir / rel).exists() for rel in _REQUIRED_MODEL_FILES)
    except PermissionError:
        return False


def _resolve_models_dir(configured: str) -> Path:
    root = Path(configured).expanduser()
    if root.name == "models" and _has_required_models(root):
        return root

    candidates = [
        root,
        root / "huggingface" / "hub" / _PDF_EXTRACT_KIT_MODEL_DIR / "snapshots",
        root / "huggingface" / _PDF_EXTRACT_KIT_MODEL_DIR / "snapshots",
        root / _PDF_EXTRACT_KIT_MODEL_DIR / "snapshots",
    ]
    for candidate in candidates:
        if candidate.name == "models" and _has_required_models(candidate):
            return candidate
        if not candidate.is_dir():
            continue
        snapshots = sorted(
            (p / "models" for p in candidate.glob("*") if (p / "models").is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for models_dir in snapshots:
            if _has_required_models(models_dir):
                return models_dir

    expected = ", ".join(_REQUIRED_MODEL_FILES)
    raise RuntimeError(f"MagicPDF models not found under {configured}. Expected files: {expected}")


def _models_config_path() -> Path:
    from magic_pdf.model.sub_modules.ocr.paddleocr2pytorch import pytorch_paddle

    return Path(pytorch_paddle.root_dir) / "pytorchocr" / "utils" / "resources" / "models_config.yml"


def _ensure_ch_doc_model_compat(models_dir: Path) -> None:
    ocr_dir = models_dir / "OCR" / "paddleocr_torch"
    expected_rec = ocr_dir / _CH_DOC_REC_MODEL
    compat_rec = ocr_dir / _CH_COMPAT_REC_MODEL
    if expected_rec.exists() or not compat_rec.exists():
        return

    cfg_path = _models_config_path()
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    lang_cfg = data.get("lang")
    ch_cfg = lang_cfg.get("ch") if isinstance(lang_cfg, dict) else None
    if not isinstance(ch_cfg, dict):
        return

    changed = False
    if ch_cfg.get("rec") != _CH_COMPAT_REC_MODEL:
        ch_cfg["rec"] = _CH_COMPAT_REC_MODEL
        changed = True
    if ch_cfg.get("dict") != _CH_COMPAT_DICT:
        ch_cfg["dict"] = _CH_COMPAT_DICT
        changed = True
    if changed:
        cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _tools_config(run_root: Path, *, device_mode: str) -> Path:
    cfg_path = run_root / "magic-pdf.json"
    model_dir = _resolve_models_dir(_MODELS_DIR)
    _ensure_ch_doc_model_compat(model_dir)
    cfg = {
        "bucket_info": {"[default]": ["", "", ""]},
        "latex-delimiter-config": {
            "display": {"left": "$$", "right": "$$"},
            "inline": {"left": "$", "right": "$"},
        },
        "device-mode": device_mode if device_mode in {"cpu", "cuda"} else "cpu",
        "models-dir": str(model_dir),
        "layout-config": {"model": "doclayout_yolo"},
        "formula-config": {"enable": _FORMULA_ENABLED},
        "table-config": {"enable": False},
    }
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg_path


def _find_markdown(run_root: Path, *, safe_stem: str, method: str) -> Path | None:
    expected = run_root / safe_stem / method / f"{safe_stem}.md"
    if expected.exists():
        return expected
    candidates = list((run_root / safe_stem / method).glob("*.md"))
    if candidates:
        return candidates[0]
    all_candidates = list(run_root.rglob("*.md"))
    if all_candidates:
        return min(all_candidates, key=lambda p: len(str(p)))
    return None


def _strip_image_refs(markdown: str) -> str:
    text = _IMAGE_MD_RE.sub("", markdown or "")
    return _IMAGE_HTML_RE.sub("", text)


def _run_magicpdf(
    *,
    file_bytes: bytes,
    filename: str,
    method: str,
    lang: str,
    debug: bool,
    device_mode: str,
    keep_artifacts: bool,
    document_id: str,
) -> dict:
    started = time.monotonic()
    method = (method or "auto").strip().lower()
    if method not in {"auto", "ocr", "txt"}:
        raise RuntimeError("method must be one of: auto, ocr, txt")

    safe_stem = _sanitize_run_id(document_id or Path(filename).stem or str(uuid.uuid4()))
    run_root = (_ARTIFACT_ROOT / safe_stem).absolute()
    run_root.mkdir(parents=True, exist_ok=True)
    input_path = run_root / f"{safe_stem}.pdf"
    input_path.write_bytes(file_bytes)

    cmd = [
        _resolve_cli(),
        "--path",
        str(input_path),
        "--output-dir",
        str(run_root),
        "--method",
        method,
    ]
    if lang:
        cmd.extend(["--lang", lang])
    if debug:
        cmd.extend(["--debug", "true"])

    env = os.environ.copy()
    env["MINERU_TOOLS_CONFIG_JSON"] = str(_tools_config(run_root, device_mode=device_mode))
    env.setdefault("YOLO_CONFIG_DIR", str(run_root / ".ultralytics"))

    stdout_text = ""
    try:
        proc = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=float(_PIPELINE_TIMEOUT_SEC),
            env=env,
        )
        stdout_text = proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"magic-pdf timed out after {_PIPELINE_TIMEOUT_SEC}s") from exc
    except subprocess.CalledProcessError as exc:
        out = (exc.stdout or "").strip()
        raise RuntimeError(f"magic-pdf failed: {out[:4000] or exc}") from exc

    md_path = _find_markdown(run_root, safe_stem=safe_stem, method=method)
    if md_path is None:
        raise RuntimeError(f"magic-pdf did not produce markdown output. Output: {stdout_text[:4000]}")

    markdown = md_path.read_text(encoding="utf-8", errors="ignore")
    asset_base_dir = str(md_path.parent)
    artifact_dir = str(run_root)

    if not keep_artifacts:
        markdown = _strip_image_refs(markdown)
        shutil.rmtree(run_root, ignore_errors=True)
        asset_base_dir = ""
        artifact_dir = ""

    return {
        "markdown": markdown,
        "parser_backend": "magicpdf",
        "artifact_dir": artifact_dir,
        "asset_base_dir": asset_base_dir,
        "method": method,
        "elapsed_sec": round(time.monotonic() - started, 3),
        "stdout_tail": stdout_text[-4000:],
    }


@app.get("/health")
def health() -> dict:
    cli = shutil.which(_CLI)
    models_dir = ""
    models_ok = False
    cuda_available = _cuda_available()
    try:
        models_dir = str(_resolve_models_dir(_MODELS_DIR))
        models_ok = True
    except RuntimeError:
        models_dir = _MODELS_DIR
    return {
        "ok": bool(cli and models_ok and (_DEFAULT_DEVICE_MODE != "cuda" or cuda_available)),
        "cli": cli or "",
        "max_concurrent_jobs": _MAX_CONCURRENT_JOBS,
        "artifact_root": str(_ARTIFACT_ROOT),
        "models_dir": models_dir,
        "models_ok": models_ok,
        "default_device_mode": _DEFAULT_DEVICE_MODE,
        "cuda_available": cuda_available,
    }


@app.post(
    "/convert",
    responses={
        400: {"description": "Invalid or empty upload"},
        500: {"description": "MagicPDF conversion failed"},
    },
)
async def convert(
    file: Annotated[UploadFile, File()],
    method: Annotated[str, Form()] = "auto",
    lang: Annotated[str, Form()] = "",
    debug: Annotated[bool, Form()] = False,
    device_mode: Annotated[str, Form()] = _DEFAULT_DEVICE_MODE,
    keep_artifacts: Annotated[bool, Form()] = False,
    document_id: Annotated[str, Form()] = "",
) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix and suffix != ".pdf":
        raise HTTPException(status_code=400, detail="MagicPDF service currently accepts PDF files only.")

    file_bytes = await _read_upload(file)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="empty upload")

    async with _semaphore:
        try:
            return await asyncio.to_thread(
                _run_magicpdf,
                file_bytes=file_bytes,
                filename=file.filename or "input.pdf",
                method=method,
                lang=lang,
                debug=bool(debug),
                device_mode=device_mode,
                keep_artifacts=bool(keep_artifacts),
                document_id=document_id,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)[:4000]) from exc
