"""
HTML parser (fallback / lightweight).

This parser is used as a robust fallback when MarkItDown is unavailable or fails.
It extracts the main readable content (best-effort) and converts it into plain text
that works well with downstream governance + chunking.
"""


from functools import lru_cache
from pathlib import Path

from langchain_core.documents import Document

from app.core.optional_deps import optional_import
from app.parsing.utils.text import read_text_file
from app.rag.preprocessing.html_xpath import extract_text_from_html


@lru_cache(maxsize=1)
def _get_readability():  # noqa: ANN202
    # Cache to avoid repeated warnings during large ingests when deps aren't installed.
    return optional_import("readability", feature="parse_html_readability", pip_name="readability-lxml")


@lru_cache(maxsize=1)
def _get_html_text():  # noqa: ANN202
    return optional_import("html_text", feature="parse_html_text_extraction")


class HtmlParser:
    """HTML document parser with readability-based main-content extraction."""

    def parse(self, file_path: Path, *, html_xpath: str | None = None) -> list[Document]:
        decoded = read_text_file(file_path)
        raw_html = decoded.text or ""
        title, extracted_html = self._extract_readability_content(raw_html)
        text, xpath_matches, xpath_error = self._extract_xpath_text(raw_html, html_xpath)
        if not text:
            text = self._extract_plain_text(extracted_html=extracted_html, raw_html=raw_html)
        metadata = self._build_metadata(
            file_path=file_path,
            decoded=decoded,
            title=title,
            html_xpath=html_xpath,
            xpath_matches=xpath_matches,
            xpath_error=xpath_error,
        )
        return [Document(page_content=text, metadata=metadata)]

    @staticmethod
    def _extract_readability_content(raw_html: str) -> tuple[str | None, str]:
        title: str | None = None
        extracted_html: str = raw_html

        # 1) Best-effort: extract "main article" using readability-lxml.
        readability = _get_readability()
        if readability is not None:
            readability_document_cls = getattr(readability, "Document", None)
            if readability_document_cls is not None:
                try:
                    rd = readability_document_cls(raw_html)
                    title = (rd.short_title() or rd.title() or None) if raw_html.strip() else None
                    extracted_html = rd.summary() or raw_html
                except Exception:
                    extracted_html = raw_html
        return title, extracted_html

    @staticmethod
    def _extract_xpath_text(raw_html: str, html_xpath: str | None) -> tuple[str, int, str | None]:
        # 2) Optional XPath extraction (when caller provides governance_html_xpath).
        xpath_matches = 0
        xpath_error: str | None = None
        if html_xpath and raw_html.strip():
            try:
                extracted = extract_text_from_html(raw_html, xpath=str(html_xpath))
                xpath_matches = int(extracted.matched_nodes or 0)
                xpath_error = extracted.xpath_error
                if xpath_matches > 0 and (extracted.text or "").strip():
                    text = extracted.text
                else:
                    text = ""
            except Exception as exc:
                text = ""
                xpath_error = f"extract_failed:{str(exc)[:120]}"
        else:
            text = ""
        return text, xpath_matches, xpath_error

    @staticmethod
    def _extract_plain_text(*, extracted_html: str, raw_html: str) -> str:
        # 3) Convert HTML to plain text.
        text = ""
        html_text = _get_html_text()
        extract_text = getattr(html_text, "extract_text", None) if html_text is not None else None
        if callable(extract_text):
            try:
                text = extract_text(extracted_html or "", guess_layout=True) or ""
            except Exception:
                text = ""
        if text:
            return text
        # Last resort: keep raw HTML (still searchable, but less clean).
        return extracted_html or raw_html or ""

    @staticmethod
    def _build_metadata(
        *,
        file_path: Path,
        decoded,
        title: str | None,
        html_xpath: str | None,
        xpath_matches: int,
        xpath_error: str | None,
    ) -> dict[str, object]:
        metadata = {
            "source": str(file_path.name),
            "file_type": "html",
            "encoding": decoded.encoding,
            "encoding_confidence": decoded.confidence,
            "encoding_had_bom": decoded.had_bom,
        }
        if title:
            metadata["title"] = title
        if html_xpath:
            metadata["html_xpath"] = str(html_xpath)
            metadata["html_xpath_matches"] = int(xpath_matches)
            if xpath_error:
                metadata["html_xpath_error"] = str(xpath_error)
        return metadata
