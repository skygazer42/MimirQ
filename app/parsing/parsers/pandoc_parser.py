"""
Pandoc-based Office/HTML -> Markdown parser.

Goals:
- Better table + image fidelity than MarkItDown for Office docs (docx/pptx).
- Optional LibreOffice fallback for legacy Office formats (doc/ppt/xls/xlsx).

This parser is intentionally optional because it relies on external CLIs:
- pandoc
- soffice (LibreOffice) for legacy formats
"""


import re
from pathlib import Path
from subprocess import PIPE, CalledProcessError, TimeoutExpired
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.utils.cli import resolve_cli_command, run_resolved_cli
from app.parsing.utils.text import read_text_file
from app.rag.core.logging import get_logger

logger = get_logger("parsing.pandoc")


def _sanitize_run_id(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value)[:120]
    return value or "pandoc"


class PandocParser:
    def __init__(self, *, force_enabled: bool = False, force_libreoffice: bool = False) -> None:
        self._enabled = bool(force_enabled) or bool(getattr(settings, "PANDOC_ENABLED", False))
        self._cli = (getattr(settings, "PANDOC_CLI", "") or "pandoc").strip() or "pandoc"
        self._timeout_sec = float(getattr(settings, "PANDOC_TIMEOUT_SEC", 180) or 180)
        self._to_format = (getattr(settings, "PANDOC_TO_FORMAT", "") or "gfm").strip() or "gfm"
        self._wrap = (getattr(settings, "PANDOC_WRAP", "") or "none").strip() or "none"
        self._extract_media = bool(getattr(settings, "PANDOC_EXTRACT_MEDIA", True))
        self._html_use_readability = bool(getattr(settings, "PANDOC_HTML_USE_READABILITY", True))

        self._lo_enabled = bool(force_libreoffice) or bool(getattr(settings, "LIBREOFFICE_ENABLED", False))
        self._lo_cli = (getattr(settings, "LIBREOFFICE_CLI", "") or "soffice").strip() or "soffice"
        self._lo_timeout_sec = float(getattr(settings, "LIBREOFFICE_TIMEOUT_SEC", 300) or 300)

        if not self._enabled:
            raise RuntimeError("Pandoc parser is disabled (PANDOC_ENABLED=false).")

        pandoc_path = resolve_cli_command(self._cli)
        if not pandoc_path:
            raise RuntimeError(f"Pandoc CLI not found: {self._cli}")
        self._pandoc_path = pandoc_path

        self._soffice_path: str | None = None
        if self._lo_enabled:
            soffice_path = resolve_cli_command(self._lo_cli)
            if not soffice_path:
                raise RuntimeError(f"LibreOffice CLI not found: {self._lo_cli}")
            self._soffice_path = soffice_path

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = _sanitize_run_id(document_id or file_path.stem or "pandoc")
        return (file_path.parent / ".pandoc" / run_id).absolute()

    def _run_pandoc(
        self,
        *,
        input_path: Path | None,
        input_text: str | None,
        cwd: Path,
        extract_media: bool,
    ) -> str:
        if bool(input_path) == bool(input_text):
            raise ValueError("pandoc requires exactly one of input_path or input_text")

        args: list[str] = [
            self._pandoc_path,
            "-t",
            self._to_format,
            f"--wrap={self._wrap}",
        ]
        if extract_media and self._extract_media:
            # Keep relative links stable (media/...) by running inside artifact_root.
            args.append("--extract-media=media")

        if input_path is not None:
            args.append(str(input_path))
            stdin = None
        else:
            args.extend(["-f", "html", "-"])  # stdin as HTML
            stdin = (input_text or "").encode("utf-8")

        try:
            proc = run_resolved_cli(
                args,
                input=stdin,
                cwd=str(cwd),
                stdout=PIPE,
                stderr=PIPE,
                timeout=self._timeout_sec,
                check=True,
            )
        except TimeoutExpired as exc:
            raise RuntimeError(f"pandoc timed out after {self._timeout_sec:.0f}s") from exc
        except CalledProcessError as exc:
            err = (exc.stderr or b"").decode("utf-8", errors="ignore")
            raise RuntimeError(f"pandoc failed: {err.strip()[:500]}") from exc

        return (proc.stdout or b"").decode("utf-8", errors="ignore")

    def _convert_via_libreoffice(self, *, file_path: Path, artifact_root: Path) -> Path:
        if not self._soffice_path:
            raise RuntimeError(
                "LibreOffice conversion requested but LIBREOFFICE_ENABLED=false or soffice is missing."
            )

        source_path = file_path.resolve(strict=False)
        ext = file_path.suffix.lower()
        if ext == ".doc":
            target_ext = "docx"
        elif ext == ".ppt":
            target_ext = "pptx"
        elif ext in {".xls", ".xlsx"}:
            # HTML keeps tables reasonably well; images may be exported next to the HTML.
            target_ext = "html"
        else:
            raise ValueError(f"LibreOffice conversion not supported for: {ext}")

        out_dir = artifact_root / "lo"
        out_dir.mkdir(parents=True, exist_ok=True)

        args = [
            self._soffice_path,
            "--headless",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            "--convert-to",
            target_ext,
            "--outdir",
            str(out_dir),
            str(source_path),
        ]
        try:
            run_resolved_cli(
                args,
                cwd=str(artifact_root),
                stdout=PIPE,
                stderr=PIPE,
                timeout=self._lo_timeout_sec,
                check=True,
            )
        except TimeoutExpired as exc:
            raise RuntimeError(f"soffice timed out after {self._lo_timeout_sec:.0f}s") from exc
        except CalledProcessError as exc:
            err = (exc.stderr or b"").decode("utf-8", errors="ignore")
            raise RuntimeError(f"soffice convert failed: {err.strip()[:500]}") from exc

        candidates = sorted(out_dir.glob(f"*.{target_ext}"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError(f"soffice produced no .{target_ext} output")

        # Prefer a name-matched candidate when possible.
        stem = (file_path.stem or "").strip().lower()
        for c in candidates:
            if (c.stem or "").strip().lower() == stem:
                return c
        return candidates[0]

    def parse(self, file_path: Path, **kwargs: Any) -> list[Document]:
        document_id = kwargs.get("document_id")
        artifact_root = self._build_artifact_root(file_path, str(document_id) if document_id else None)

        ext = file_path.suffix.lower()
        title: str | None = None

        # HTML: best-effort readability extraction, keep local image refs (no media extraction).
        if ext in {".html", ".htm"}:
            decoded = read_text_file(file_path)
            raw_html = decoded.text or ""
            html_text = raw_html
            if self._html_use_readability and raw_html.strip():
                try:
                    from readability import Document as ReadabilityDocument  # type: ignore

                    rd = ReadabilityDocument(raw_html)
                    title = (rd.short_title() or rd.title() or None) if raw_html.strip() else None
                    html_text = rd.summary() or raw_html
                except Exception:
                    html_text = raw_html

            markdown = self._run_pandoc(
                input_path=None,
                input_text=html_text,
                cwd=file_path.parent,
                extract_media=False,
            )
            metadata = {
                "source": str(file_path.name),
                "file_type": ext.lstrip("."),
                "parser_backend": "pandoc",
                "encoding": decoded.encoding,
                "encoding_confidence": decoded.confidence,
                "encoding_had_bom": decoded.had_bom,
                # For local <img src="..."> refs in HTML.
                "asset_base_dir": str(file_path.parent.resolve(strict=False)),
            }
            if title:
                metadata["title"] = title
            return [Document(page_content=markdown, metadata=metadata)]

        # Legacy Office: convert to a Pandoc-readable format via LibreOffice first.
        pandoc_input = file_path
        if ext in {".doc", ".ppt", ".xls", ".xlsx"}:
            artifact_root.mkdir(parents=True, exist_ok=True)
            pandoc_input = self._convert_via_libreoffice(file_path=file_path, artifact_root=artifact_root)
            ext = pandoc_input.suffix.lower()

        # Formats Pandoc can read directly.
        # Notes:
        # - .docx/.pptx: Office formats (image extraction is common)
        # - .epub/.rtf/.odt: common "document-like" formats (Phase1 coverage)
        if ext not in {".docx", ".pptx", ".epub", ".rtf", ".odt"}:
            raise ValueError(f"Pandoc parser does not support: {file_path.suffix.lower()}")

        artifact_root.mkdir(parents=True, exist_ok=True)
        markdown = self._run_pandoc(
            input_path=pandoc_input,
            input_text=None,
            cwd=artifact_root,
            extract_media=True,
        )
        metadata = {
            "source": str(file_path.name),
            "file_type": file_path.suffix.lstrip("."),
            "parser_backend": "pandoc",
            "asset_base_dir": str(artifact_root),
            "artifact_dir": str(artifact_root),
            "pandoc_input": str(pandoc_input.name),
        }
        return [Document(page_content=markdown, metadata=metadata)]
