"""
Pandoc-based Office/HTML -> Markdown parser.

Goals:
- Better table + image fidelity than MarkItDown for Office docs (docx/pptx).
- Optional LibreOffice fallback for legacy Office formats (doc/ppt/xls/xlsx).

This parser is intentionally optional because it relies on external CLIs:
- pandoc
- soffice (LibreOffice) for legacy formats
"""

import logging
from pathlib import Path
from subprocess import PIPE, CalledProcessError, TimeoutExpired
from typing import Any

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.rag.ingestion.parsing.utils.artifact_normalizer import sanitize_artifact_run_id
from app.rag.ingestion.parsing.utils.cli import resolve_cli_command, run_resolved_cli
from app.rag.ingestion.parsing.utils.text import read_text_file

logger = logging.getLogger("parsing.pandoc")


class PandocParser:
    def __init__(self, *, force_enabled: bool = False, force_libreoffice: bool = False) -> None:
        enabled = force_enabled or settings.PANDOC_ENABLED
        cli = settings.PANDOC_CLI.strip()
        self._timeout_sec = settings.PANDOC_TIMEOUT_SEC
        self._to_format = settings.PANDOC_TO_FORMAT.strip()
        self._wrap = settings.PANDOC_WRAP.strip()
        self._extract_media = settings.PANDOC_EXTRACT_MEDIA
        self._html_use_readability = settings.PANDOC_HTML_USE_READABILITY

        lo_enabled = force_libreoffice or settings.LIBREOFFICE_ENABLED
        lo_cli = settings.LIBREOFFICE_CLI.strip()
        self._lo_timeout_sec = settings.LIBREOFFICE_TIMEOUT_SEC

        if not enabled:
            raise RuntimeError("Pandoc parser is disabled (PANDOC_ENABLED=false).")

        pandoc_path = resolve_cli_command(cli)
        if not pandoc_path:
            raise RuntimeError(f"Pandoc CLI not found: {cli}")
        self._pandoc_path = pandoc_path

        self._soffice_path: str | None = None
        if lo_enabled:
            soffice_path = resolve_cli_command(lo_cli)
            if not soffice_path:
                raise RuntimeError(f"LibreOffice CLI not found: {lo_cli}")
            self._soffice_path = soffice_path

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = sanitize_artifact_run_id(document_id or file_path.stem or "pandoc", fallback="pandoc")
        return (file_path.parent / ".pandoc" / run_id).absolute()

    def _run_pandoc(
        self,
        *,
        input_path: Path | None,
        input_text: str | None,
        cwd: Path,
        extract_media: bool,
    ) -> str:
        if (input_path is None) == (input_text is None):
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
            stdin = input_text.encode("utf-8")

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
            err = (b"" if exc.stderr is None else exc.stderr).decode("utf-8", errors="replace")
            raise RuntimeError(f"pandoc failed: {err.strip()[:500]}") from exc

        return proc.stdout.decode("utf-8")

    def _convert_via_libreoffice(self, *, file_path: Path, artifact_root: Path) -> Path:
        if not self._soffice_path:
            raise RuntimeError("LibreOffice conversion requested but LIBREOFFICE_ENABLED=false or soffice is missing.")

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
            err = (b"" if exc.stderr is None else exc.stderr).decode("utf-8", errors="replace")
            raise RuntimeError(f"soffice convert failed: {err.strip()[:500]}") from exc

        candidates = sorted(out_dir.glob(f"*.{target_ext}"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError(f"soffice produced no .{target_ext} output")

        # Prefer a name-matched candidate when possible.
        stem = (file_path.stem).strip().lower()
        for c in candidates:
            if (c.stem).strip().lower() == stem:
                return c
        raise RuntimeError(f"soffice produced no name-matched .{target_ext} output for {file_path.name}")

    def parse(self, file_path: Path, **kwargs: Any) -> list[Document]:
        document_id = kwargs.get("document_id")
        artifact_root = self._build_artifact_root(file_path, document_id)

        ext = file_path.suffix.lower()
        title: str | None = None

        # HTML: best-effort readability extraction, keep local image refs (no media extraction).
        if ext in {".html", ".htm"}:
            decoded = read_text_file(file_path)
            html_text = decoded.text
            if self._html_use_readability and html_text.strip():
                try:
                    from readability import Document as ReadabilityDocument  # type: ignore

                    rd = ReadabilityDocument(html_text)
                    title = rd.short_title() or rd.title() or None
                    html_text = rd.summary() or html_text
                except Exception as exc:
                    logger.debug("[pandoc] readability extraction failed; using original HTML: %s", exc)

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
        # - .html: LibreOffice output for spreadsheets
        if ext not in {".docx", ".pptx", ".epub", ".rtf", ".odt", ".html"}:
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
