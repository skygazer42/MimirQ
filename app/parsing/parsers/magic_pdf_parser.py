"""
MagicPDF (magic-pdf) parser adapter.

MagicPDF is an optional, local advanced PDF parser that can output Markdown +
images. It is typically heavyweight (torch/transformers). We integrate it via
its CLI entrypoint (`magic-pdf`) so the backend can treat it as a pluggable
parser backend.
"""


import json
import os
import re
import shutil
from pathlib import Path
from subprocess import PIPE, STDOUT, CalledProcessError, TimeoutExpired
from typing import Any

import requests
from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.utils.cli import resolve_cli_command, run_resolved_cli
from app.parsing.utils.markdown_response import extract_markdown_response_text
from app.rag.core.logging import get_logger

from .service_url_fallback import build_docker_service_url_candidates

logger = get_logger("parsing.magicpdf")

MAGIC_PDF_MODEL_ROOT_CANDIDATES = (
    "/opt/mimirq-model-cache/huggingface/hub/models--opendatalab--PDF-Extract-Kit-1.0/snapshots",
    "/opt/mimirq-model-cache/huggingface/models--opendatalab--PDF-Extract-Kit-1.0/snapshots",
    "/root/.cache/huggingface/hub/models--opendatalab--PDF-Extract-Kit-1.0/snapshots",
)
MAGIC_PDF_REQUIRED_MODEL_FILES = (
    "Layout/YOLO/doclayout_yolo_docstructbench_imgsz1280_2501.pt",
    # MagicPDF 1.3.x switches CPU OCR to ch_lite, which expects the v3 detector
    # even when newer PDF-Extract-Kit snapshots already contain v5 OCR weights.
    "OCR/paddleocr_torch/ch_PP-OCRv3_det_infer.pth",
    "OCR/paddleocr_torch/ch_PP-OCRv5_rec_infer.pth",
)
MAGIC_PDF_SERVICE_HOSTNAMES = {"mimirq-magicpdf"}


def magicpdf_service_configured(configured_url: str | None = None) -> bool:
    return bool((configured_url if configured_url is not None else getattr(settings, "MAGIC_PDF_API_URL", "") or "").strip())


def _has_required_magicpdf_models(models_dir: Path) -> bool:
    try:
        return all((models_dir / rel).exists() for rel in MAGIC_PDF_REQUIRED_MODEL_FILES)
    except PermissionError:
        return False


def _is_dir_readable(path: Path) -> bool:
    try:
        return path.is_dir()
    except PermissionError:
        return False


def _resolve_magicpdf_candidate(candidate: Path) -> Path | None:
    if candidate.name == "models" and _has_required_magicpdf_models(candidate):
        return candidate
    if _is_dir_readable(candidate):
        snapshots = sorted(
            (p / "models" for p in candidate.glob("*") if (p / "models").is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for models_dir in snapshots:
            if _has_required_magicpdf_models(models_dir):
                return models_dir
    return None


def resolve_magicpdf_models_dir(configured: str | None = None) -> Path | None:
    """
    Locate a PDF-Extract-Kit models directory usable by MagicPDF.

    MinerU local deployments already cache PDF-Extract-Kit under the shared
    Hugging Face cache. The API/worker containers mount that cache read-only
    and this resolver picks a snapshot containing the MagicPDF 1.3.x local
    model files instead of creating an empty ~/.cache/magicpdf/models directory.
    """
    raw = (configured or os.environ.get("MAGIC_PDF_MODELS_DIR") or "").strip()
    candidates: list[Path] = []
    if raw:
        return _resolve_magicpdf_candidate(Path(raw).expanduser())

    repo_root = Path(__file__).resolve().parents[3]
    candidates.append(
        repo_root
        / "app"
        / "deepdoc"
        / "resources"
        / "models"
        / "magicpdf"
        / "PDF-Extract-Kit-1.0"
        / "models"
    )

    home = Path.home()
    candidates.append(home / ".cache" / "magicpdf" / "models")
    candidates.append(
        home
        / ".cache"
        / "huggingface"
        / "hub"
        / "models--opendatalab--PDF-Extract-Kit-1.0"
        / "snapshots"
    )
    for root in MAGIC_PDF_MODEL_ROOT_CANDIDATES:
        candidates.append(Path(root))

    for candidate in candidates:
        resolved = _resolve_magicpdf_candidate(candidate)
        if resolved is not None:
            return resolved
    return None


class MagicPDFParser:
    def __init__(self) -> None:
        self._cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
        self._api_url = (getattr(settings, "MAGIC_PDF_API_URL", "") or "").strip()
        self._request_timeout_sec = float(getattr(settings, "MAGIC_PDF_REQUEST_TIMEOUT_SEC", 600) or 600)
        self._session = requests.Session()

    @staticmethod
    def required_model_files() -> tuple[str, ...]:
        return MAGIC_PDF_REQUIRED_MODEL_FILES

    def _ensure_cli(self) -> str:
        resolved = resolve_cli_command(self._cli) if self._cli else None
        if resolved:
            return str(resolved)
        raise RuntimeError(
            f"MagicPDF CLI not found: {self._cli!r}. "
            "Install `magic-pdf` and ensure `magic-pdf` is on PATH (or run the backend with the same conda/venv), "
            "or set MAGIC_PDF_CLI to the full path of the executable."
        )

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        # Keep artifacts alongside the uploaded file so downstream stages can
        # access generated images before cleanup.
        run_id = (document_id or file_path.stem or "magicpdf").strip()
        run_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", run_id)[:120] or "magicpdf"
        return file_path.parent / ".magicpdf" / run_id

    def _resolve_method(self) -> str:
        method = (getattr(settings, "MAGIC_PDF_METHOD", "") or "auto").strip().lower()
        if method not in {"auto", "ocr", "txt"}:
            raise ValueError("MAGIC_PDF_METHOD must be one of: auto, ocr, txt")
        return method

    def _candidate_api_urls(self) -> list[str]:
        return build_docker_service_url_candidates(
            self._api_url,
            service_hostnames=MAGIC_PDF_SERVICE_HOSTNAMES,
        )

    def _post_service_multipart(self, *, file_path: Path, document_id: str | None) -> requests.Response:
        file_bytes = file_path.read_bytes()
        content_type = "application/pdf" if file_path.suffix.lower() == ".pdf" else "application/octet-stream"
        files = {"file": (file_path.name, file_bytes, content_type)}
        data = {
            "method": self._resolve_method(),
            "debug": str(bool(getattr(settings, "MAGIC_PDF_DEBUG", False))).lower(),
            "device_mode": (getattr(settings, "MAGIC_PDF_DEVICE_MODE", "") or "cuda").strip().lower() or "cuda",
            "keep_artifacts": str(bool(getattr(settings, "MAGIC_PDF_KEEP_ARTIFACTS", False))).lower(),
        }
        lang = (getattr(settings, "MAGIC_PDF_LANG", "") or "").strip()
        if lang:
            data["lang"] = lang
        if document_id:
            data["document_id"] = str(document_id)

        candidate_urls = self._candidate_api_urls()
        last_error: Exception | None = None
        for index, url in enumerate(candidate_urls):
            try:
                return self._session.post(url, files=files, data=data, timeout=self._request_timeout_sec)
            except requests.RequestException as exc:
                last_error = exc
                if index == len(candidate_urls) - 1:
                    raise
                logger.warning(
                    "[magicpdf] request to %s failed (%s); retrying fallback %s",
                    url,
                    exc.__class__.__name__,
                    candidate_urls[index + 1],
                )
        if last_error is not None:
            raise last_error
        raise RuntimeError("MagicPDF service parser requires MAGIC_PDF_API_URL.")

    @staticmethod
    def _extract_service_markdown(data: Any) -> str:
        return extract_markdown_response_text(data)

    def _parse_service(
        self,
        file_path: Path,
        *,
        dataset_id: str | None,
        document_id: str | None,
    ) -> list[Document]:
        if not self._api_url:
            raise RuntimeError("MagicPDF service parser requires MAGIC_PDF_API_URL.")

        logger.info("[magicpdf] parsing %s via service", file_path.name)
        resp = self._post_service_multipart(file_path=file_path, document_id=document_id)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise RuntimeError(f"MagicPDF service API error {resp.status_code}: {(resp.text or '')[:500]}")

        data: Any = {}
        markdown_text = ""
        ctype = str(resp.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            try:
                data = resp.json()
            except Exception:
                data = json.loads((resp.text or "").strip() or "{}")
            markdown_text = self._extract_service_markdown(data)
        else:
            markdown_text = resp.text or ""

        if not str(markdown_text or "").strip():
            raise RuntimeError("MagicPDF service returned empty Markdown.")

        method = self._resolve_method()
        if isinstance(data, dict):
            method = str(data.get("method") or method)

        metadata: dict[str, Any] = {
            "source": str(file_path.name),
            "file_type": "pdf",
            "parser_backend": "magicpdf",
            "magicpdf_method": method,
            "magicpdf_mode": "service",
        }
        if dataset_id:
            metadata["dataset_id"] = str(dataset_id)
        if isinstance(data, dict):
            if data.get("asset_base_dir"):
                metadata["asset_base_dir"] = str(data["asset_base_dir"])
            if data.get("artifact_dir"):
                metadata["artifact_dir"] = str(data["artifact_dir"])
            if data.get("elapsed_sec") is not None:
                try:
                    metadata["magicpdf_elapsed_sec"] = float(data["elapsed_sec"])
                except (TypeError, ValueError):
                    metadata["magicpdf_elapsed_sec"] = data["elapsed_sec"]

        return [Document(page_content=markdown_text, metadata=metadata)]

    def _ensure_tools_config(self, artifact_root: Path) -> Path:
        """
        MagicPDF requires a config JSON (defaults to `~/magic-pdf.json`) and will
        crash early if it's missing.

        We generate a minimal config per-run and point the subprocess at it via
        the `MINERU_TOOLS_CONFIG_JSON` env var.
        """
        configured = (getattr(settings, "MINERU_TOOLS_CONFIG_JSON", "") or "").strip()
        if not configured:
            configured = (os.environ.get("MINERU_TOOLS_CONFIG_JSON") or "").strip()
        if configured:
            configured_path = Path(configured)
            if not configured_path.is_absolute():
                configured_path = Path.home() / configured_path
            if configured_path.exists():
                return configured_path
            logger.warning("[magicpdf] MINERU_TOOLS_CONFIG_JSON is set but not found: %s", configured_path)

        cfg_path = artifact_root / "magic-pdf.json"
        if cfg_path.exists():
            return cfg_path

        models_dir = resolve_magicpdf_models_dir(getattr(settings, "MAGIC_PDF_MODELS_DIR", ""))
        if models_dir is None:
            expected = ", ".join(MAGIC_PDF_REQUIRED_MODEL_FILES)
            raise RuntimeError(
                "MagicPDF local models not found. Mount a PDF-Extract-Kit model cache "
                "or set MAGIC_PDF_MODELS_DIR to a directory containing: "
                f"{expected}"
            )
        device_mode = (getattr(settings, "MAGIC_PDF_DEVICE_MODE", "") or "cpu").strip().lower()
        if device_mode not in {"cpu", "cuda"}:
            device_mode = "cpu"

        cfg = {
            "bucket_info": {"[default]": ["", "", ""]},
            "latex-delimiter-config": {
                "display": {"left": "$$", "right": "$$"},
                "inline": {"left": "$", "right": "$"},
            },
            "device-mode": device_mode,
            "models-dir": str(models_dir),
            # Prefer the lightweight YOLO layout model (weights live in the PDF-Extract-Kit pipeline).
            "layout-config": {"model": "doclayout_yolo"},
            # Keep formula recognition off by default to avoid heavy Unimernet deps and
            # version coupling issues with `transformers` generation APIs. Enable explicitly
            # via MAGIC_PDF_FORMULA_ENABLED=true when the runtime has the required deps.
            "formula-config": {"enable": bool(getattr(settings, "MAGIC_PDF_FORMULA_ENABLED", False))},
            # Keep table recognition off by default for the local fallback. The
            # dedicated Docling/ETL4LLM/Marker paths cover table-heavy documents
            # and avoid forcing extra MagicPDF table weights for basic local
            # availability checks.
            "table-config": {"enable": False},
        }
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return cfg_path

    def parse(
        self,
        file_path: Path,
        *,
        dataset_id: str | None = None,  # kept for interface parity
        document_id: str | None = None,
        **_kwargs,
    ) -> list[Document]:
        _ = dataset_id
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if self._api_url:
            return self._parse_service(file_path, dataset_id=dataset_id, document_id=document_id)

        cli = self._ensure_cli()
        method = self._resolve_method()
        lang = (getattr(settings, "MAGIC_PDF_LANG", "") or "").strip() or None
        debug = bool(getattr(settings, "MAGIC_PDF_DEBUG", False))
        timeout_sec = float(getattr(settings, "MAGIC_PDF_TIMEOUT_SEC", 600) or 600)

        artifact_root = self._build_artifact_root(file_path, document_id)
        artifact_root = artifact_root.absolute()
        artifact_root.mkdir(parents=True, exist_ok=True)

        # Avoid spaces/unicode in the input filename (some parsers/tools are brittle).
        safe_stem = artifact_root.name
        safe_pdf_path = artifact_root / f"{safe_stem}.pdf"
        if safe_pdf_path.resolve() != file_path.resolve():
            shutil.copyfile(file_path, safe_pdf_path)

        cmd: list[str] = [
            cli,
            "--path",
            str(safe_pdf_path),
            "--output-dir",
            str(artifact_root),
            "--method",
            method,
        ]
        if lang:
            cmd.extend(["--lang", lang])
        if debug:
            cmd.extend(["--debug", "true"])

        logger.info("[magicpdf] parsing %s (method=%s)", file_path.name, method)
        env = os.environ.copy()
        env["MINERU_TOOLS_CONFIG_JSON"] = str(self._ensure_tools_config(artifact_root))
        env.setdefault("YOLO_CONFIG_DIR", str(artifact_root / ".ultralytics"))
        stdout_text = ""
        try:
            proc = run_resolved_cli(
                cmd,
                check=True,
                stdout=PIPE,
                stderr=STDOUT,
                text=True,
                timeout=timeout_sec,
                env=env,
            )
            stdout_text = proc.stdout or ""
            if stdout_text:
                logger.info("[magicpdf] %s", stdout_text.strip()[:4000])
        except TimeoutExpired as exc:
            raise RuntimeError(f"MagicPDF timed out after {timeout_sec:.0f}s") from exc
        except CalledProcessError as exc:
            out = (exc.stdout or "").strip()
            raise RuntimeError(f"MagicPDF failed: {out[:4000] or exc}") from exc

        md_path = artifact_root / safe_stem / method / f"{safe_stem}.md"
        if not md_path.exists():
            # Best-effort: locate any markdown output.
            candidates = list((artifact_root / safe_stem / method).glob("*.md"))
            if candidates:
                md_path = candidates[0]
        if not md_path.exists():
            out = stdout_text.strip()
            if out:
                # Keep the full CLI output for debugging. This is particularly helpful
                # because the upstream CLI sometimes exits with code 0 on failures.
                try:
                    (artifact_root / "magic-pdf.log").write_text(stdout_text, encoding="utf-8", errors="ignore")
                except Exception:
                    pass
                raise RuntimeError(f"MagicPDF did not produce a markdown output file. Output:\n{out[:4000]}")
            raise RuntimeError("MagicPDF did not produce a markdown output file")

        markdown_text = md_path.read_text(encoding="utf-8", errors="ignore")

        # If object storage is disabled, strip local image references to avoid dead links.
        if not settings.MINIO_ENABLED and markdown_text:
            markdown_text = re.sub(r"!\[[^\]]*\]\(\s*[^)\s]+?\s*\)\s*", "", markdown_text)
            markdown_text = re.sub(r"<img[^>]*?>", "", markdown_text, flags=re.IGNORECASE)

        metadata = {
            "source": str(file_path.name),
            "file_type": "pdf",
            "parser_backend": "magicpdf",
            # Used by downstream stages to resolve relative image paths like "images/foo.png".
            "asset_base_dir": str(md_path.parent),
            # Used for best-effort cleanup after ingestion.
            "artifact_dir": str(artifact_root),
            "magicpdf_method": method,
        }
        if lang:
            metadata["magicpdf_lang"] = lang

        return [Document(page_content=markdown_text, metadata=metadata)]
