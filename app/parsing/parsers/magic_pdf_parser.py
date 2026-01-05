"""
MagicPDF (magic-pdf) parser adapter.

MagicPDF is an optional, local advanced PDF parser that can output Markdown +
images. It is typically heavyweight (torch/transformers). We integrate it via
its CLI entrypoint (`magic-pdf`) so the backend can treat it as a pluggable
parser backend.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.logging import get_logger


logger = get_logger("parsing.magicpdf")


class MagicPDFParser:
    def __init__(self) -> None:
        self._cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"

    def _ensure_cli(self) -> str:
        resolved = shutil.which(self._cli) if self._cli else None
        if resolved:
            return resolved
        raise RuntimeError(
            f"MagicPDF CLI not found: {self._cli!r}. "
            "Install `magic-pdf` and ensure `magic-pdf` is on PATH, "
            "or set MAGIC_PDF_CLI to the full path."
        )

    def _build_artifact_root(self, file_path: Path, document_id: Optional[str]) -> Path:
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

    def parse(
        self,
        file_path: Path,
        *,
        dataset_id: Optional[str] = None,  # kept for interface parity
        document_id: Optional[str] = None,
        **_kwargs,
    ) -> List[Document]:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        cli = self._ensure_cli()
        method = self._resolve_method()
        lang = (getattr(settings, "MAGIC_PDF_LANG", "") or "").strip() or None
        debug = bool(getattr(settings, "MAGIC_PDF_DEBUG", False))
        timeout_sec = float(getattr(settings, "MAGIC_PDF_TIMEOUT_SEC", 600) or 600)

        artifact_root = self._build_artifact_root(file_path, document_id)
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
        try:
            proc = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_sec,
                env=os.environ.copy(),
            )
            if proc.stdout:
                logger.info("[magicpdf] %s", proc.stdout.strip()[:4000])
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"MagicPDF timed out after {timeout_sec:.0f}s") from exc
        except subprocess.CalledProcessError as exc:
            out = (exc.stdout or "").strip()
            raise RuntimeError(f"MagicPDF failed: {out[:4000] or exc}") from exc

        md_path = artifact_root / safe_stem / method / f"{safe_stem}.md"
        if not md_path.exists():
            # Best-effort: locate any markdown output.
            candidates = list((artifact_root / safe_stem / method).glob("*.md"))
            if candidates:
                md_path = candidates[0]
        if not md_path.exists():
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

