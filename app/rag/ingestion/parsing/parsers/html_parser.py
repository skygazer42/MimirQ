#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

"""
HTML parser (fallback / lightweight).

This parser is used as a robust fallback when MarkItDown is unavailable or fails.
It extracts the main readable content (best-effort) and converts it into plain text
that works well with downstream governance + chunking.
"""

import logging
from functools import lru_cache
from pathlib import Path

from langchain_core.documents import Document

from app.infrastructure.runtime.dependencies import optional_import, require_dependency
from app.rag.ingestion.governance.markup.html_xpath import extract_text_from_html
from app.rag.ingestion.parsing.utils.text import DecodedText, read_text_file, read_text_source

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_readability():  # noqa: ANN202
    # Cache to avoid repeated warnings during large ingests when deps aren't installed.
    return optional_import("readability", feature="parse_html_readability", pip_name="readability-lxml")


@lru_cache(maxsize=1)
def _get_html_text():  # noqa: ANN202
    return optional_import("html_text", feature="parse_html_text_extraction")


def _extract_readability_content(raw_html: str) -> tuple[str | None, str]:
    title: str | None = None
    extracted_html: str = raw_html

    # 1) Best-effort: extract "main article" using readability-lxml.
    readability = _get_readability()
    if readability is not None:
        try:
            rd = readability.Document(raw_html)
            title = (rd.short_title() or rd.title() or None) if raw_html.strip() else None
            extracted_html = rd.summary() or raw_html
        except Exception:
            logger.debug("Optional HTML readability extraction failed; using source HTML", exc_info=True)
            extracted_html = raw_html
    return title, extracted_html


def _extract_xpath_text(raw_html: str, html_xpath: str | None) -> tuple[str, int, str | None]:
    # 2) Optional XPath extraction (when caller provides governance_html_xpath).
    xpath_matches = 0
    xpath_error: str | None = None
    if html_xpath is not None and html_xpath.strip() and raw_html.strip():
        extracted = extract_text_from_html(raw_html, xpath=html_xpath)
        xpath_matches = extracted.matched_nodes
        xpath_error = extracted.xpath_error
        if xpath_error is not None:
            if xpath_error.startswith(("xpath_failed:", "parse_failed:")):
                raise ValueError(f"HTML XPath extraction failed: {xpath_error}")
            raise RuntimeError(f"HTML XPath extraction unavailable: {xpath_error}")
        text = extracted.text
    else:
        text = ""
    return text, xpath_matches, xpath_error


def _extract_plain_text(*, extracted_html: str, raw_html: str) -> str:
    # 3) Convert HTML to plain text.
    text = ""
    html_text = _get_html_text()
    if html_text is not None:
        try:
            text = html_text.extract_text(extracted_html, guess_layout=True)
        except Exception:
            logger.debug("Optional HTML text extraction failed; retaining source HTML", exc_info=True)
            text = ""
    if text:
        return text
    # Last resort: keep raw HTML (still searchable, but less clean).
    return extracted_html or raw_html


def _build_metadata(
    *,
    file_path: Path,
    decoded: DecodedText,
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
        metadata["html_xpath_matches"] = xpath_matches
        if xpath_error:
            metadata["html_xpath_error"] = str(xpath_error)
    return metadata


class HtmlParser:
    """HTML document parser with readability-based main-content extraction."""

    def parse(self, file_path: Path, *, html_xpath: str | None = None) -> list[Document]:
        decoded = read_text_file(file_path)
        raw_html = decoded.text
        title, extracted_html = _extract_readability_content(raw_html)
        text, xpath_matches, xpath_error = _extract_xpath_text(raw_html, html_xpath)
        xpath_fallback = bool(html_xpath is not None and html_xpath.strip() and not text.strip())
        if not text:
            text = _extract_plain_text(extracted_html=extracted_html, raw_html=raw_html)
        metadata = _build_metadata(
            file_path=file_path,
            decoded=decoded,
            title=title,
            html_xpath=html_xpath,
            xpath_matches=xpath_matches,
            xpath_error=xpath_error,
        )
        if xpath_fallback:
            metadata["html_xpath_fallback"] = True
        return [Document(page_content=text, metadata=metadata)]


def extract_html_sections(txt: str) -> list[str]:
    """Extract strict title/content sections for the integrated chunking consumers."""
    if not isinstance(txt, str):
        raise TypeError("txt type should be str!")
    readability = require_dependency("readability", feature="parse_html_sections", pip_name="readability-lxml")
    html_text = require_dependency("html_text", feature="parse_html_sections")
    html_doc = readability.Document(txt)
    title = html_doc.title()
    content = html_text.extract_text(html_doc.summary(html_partial=True))
    return f"{title}\n{content}".split("\n")


def parse_html_sections(filename: str, binary: bytes | None = None) -> list[str]:
    return extract_html_sections(read_text_source(filename, binary))
