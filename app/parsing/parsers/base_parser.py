"""
Advanced parser base class.
"""


import asyncio
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.rag.core.logging import get_logger

_POSITION_TAG_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")
_SECTION_KINDS = {"text", "equation", "table", "image"}


class BaseAdvancedParser(ABC):
    """
    Advanced parser abstract base class.

    Provides:
    - Lazy loading of the underlying parser
    - File validation
    - Convert sections/tables to LangChain Document
    - Async wrapper

    Subclasses must implement:
    - _create_parser(): create underlying parser instance
    - _get_parser_name(): return parser name (for logs/metadata)
    - _check_parser_installation(): check parser availability
    - _call_parse_method(): call underlying parse method
    """

    # Subclasses can override; None means no extension check.
    SUPPORTED_EXTENSIONS: set[str] | None = None

    def __init__(self):
        self._parser = None
        self._logger = logging.getLogger(f"parsing.{self._get_parser_name()}_parser")

    def _get_parser(self):
        """Lazy-load the underlying parser."""
        if self._parser is not None:
            return self._parser
        self._parser = self._create_parser()
        return self._parser

    @abstractmethod
    def _create_parser(self) -> Any:
        """
        Create underlying parser instance.

        Returns:
            Parser instance.
        """
        pass

    @abstractmethod
    def _get_parser_name(self) -> str:
        """
        Return parser name (for logs and metadata).

        Returns:
            Parser name, e.g. "mineru", "docling", "tcadp".
        """
        pass

    @abstractmethod
    def _check_parser_installation(self, parser: Any) -> tuple[bool, str]:
        """
        Check parser availability.

        Args:
            parser: Underlying parser instance.

        Returns:
            (is_available, reason/error message)
        """
        pass

    @abstractmethod
    def _call_parse_method(
        self,
        parser: Any,
        file_path: Path,
        binary: bytes | None,
        callback: Callable[[float, str], None],
        **kwargs
    ) -> tuple[list, list]:
        """
        Call the underlying parser's parse method.

        Args:
            parser: Underlying parser instance.
            file_path: File path.
            binary: Optional file bytes. Prefer passing None so the underlying parser can
                stream/read from disk without duplicating the file in memory.
            callback: Progress callback.
            **kwargs: Extra args.

        Returns:
            (sections, tables)
        """
        pass

    def check_installation(self) -> bool:
        """Check whether parser is available."""
        parser = self._get_parser()
        ok, reason = self._check_parser_installation(parser)
        if not ok:
            self._logger.warning(f"{self._get_parser_name()} check failed: {reason}")
        return ok

    def _validate_file(self, file_path: Path) -> None:
        """
        Validate file path and extension.

        Args:
            file_path: File path.

        Raises:
            FileNotFoundError: File not found.
            ValueError: Unsupported file type.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if self.SUPPORTED_EXTENSIONS is not None:
            if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                raise ValueError(
                    f"Unsupported file type: {file_path.suffix}. "
                    f"Supported: {self.SUPPORTED_EXTENSIONS}"
                )

    def _create_callback(self) -> Callable[[float, str], None]:
        """Create a progress callback."""
        parser_name = self._get_parser_name().upper()
        def callback(progress: float, msg: str):
            self._logger.info(f"[{parser_name}] {progress:.0%} - {msg}")
        return callback

    def _convert_sections_to_documents(
        self,
        sections: list,
        base_metadata: dict
    ) -> list[Document]:
        """
        Convert sections to a list of Documents.

        Args:
            sections: Sections returned by underlying parser.
            base_metadata: Base metadata.

        Returns:
            List of Documents.
        """
        if not sections:
            return []

        def _positions_from_tag(tag: str) -> list[tuple[int, float, float, float, float]]:
            match = _POSITION_TAG_RE.search(tag or "")
            if not match:
                return []
            page_tokens = [p for p in str(match.group(1) or "").split("-") if p.strip()]
            left = float(match.group(2))
            right = float(match.group(3))
            top = float(match.group(4))
            bottom = float(match.group(5))
            out: list[tuple[int, float, float, float, float]] = []
            for token in page_tokens:
                try:
                    out.append((max(0, int(token) - 1), left, right, top, bottom))
                except Exception:
                    get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                    continue
            return out

        def _normalize_section(section: Any) -> tuple[str, str | None, str | None]:
            if isinstance(section, tuple):
                head = section[0] if section else ""
                text = str(head or "").strip()
                if not text:
                    return "", None, None

                # Preserve position tags from parsers like Docling/MinerU that return (text, tag)
                # or (text, type, tag). The integrated integrated pipeline relies on `@@...##` tags.
                tag = ""
                section_kind = None
                for item in reversed(section[1:]):
                    if not isinstance(item, str):
                        continue
                    candidate = item.strip()
                    if "@@" in candidate and "##" in candidate and _POSITION_TAG_RE.search(candidate):
                        tag = candidate
                        continue
                    normalized = candidate.lower()
                    if normalized in _SECTION_KINDS:
                        section_kind = normalized
                if tag and tag not in text:
                    text = f"{text}{tag}"
                return text, tag or None, section_kind

            return str(section or "").strip(), None, None

        documents: list[Document] = []
        text_parts: list[str] = []
        for section in sections:
            text, tag, section_kind = _normalize_section(section)
            if text:
                if section_kind == "equation":
                    clean_text = _POSITION_TAG_RE.sub("", text).strip()
                    meta = {
                        **base_metadata,
                        "content_type": "equation",
                        "doc_type_kwd": "equation",
                        "element_kind": "equation",
                        "element_text": clean_text or text,
                    }
                    positions = _positions_from_tag(tag or "")
                    if positions:
                        meta["positions"] = positions
                        first = positions[0]
                        meta["element_page"] = int(first[0]) + 1
                        meta["element_bbox"] = {
                            "x0": int(first[1]),
                            "x1": int(first[2]),
                            "y0": int(first[3]),
                            "y1": int(first[4]),
                        }
                    documents.append(Document(page_content=text, metadata=meta))
                    continue
                text_parts.append(text)

        if not text_parts:
            return documents

        merged_text = "\n\n".join(text_parts)
        documents.insert(
            0,
            Document(
                page_content=merged_text,
                metadata={**base_metadata, "content_type": "text", "element_kind": "paragraph", "element_text": merged_text},
            ),
        )
        return documents

    def _convert_tables_to_documents(
        self,
        tables: list,
        base_metadata: dict
    ) -> list[Document]:
        """
        Convert tables to a list of Documents.

        Args:
            tables: Tables returned by underlying parser.
            base_metadata: Base metadata.

        Returns:
            List of Documents.
        """
        if not tables:
            return []

        documents = []
        for i, table in enumerate(tables):
            table_content = self._extract_table_content(table)

            if table_content and table_content.strip():
                documents.append(Document(
                    page_content=table_content,
                    metadata={
                        **base_metadata,
                        "content_type": "table",
                        "table_index": i,
                    }
                ))

            # If the underlying parser provides a cropped image (e.g., Docling tables/figures),
            # emit an additional image Document so downstream can upload it to MinIO and preview it.
            try:
                image_obj = None
                positions = None
                if isinstance(table, tuple) and len(table) >= 1:
                    table_data = table[0]
                    if isinstance(table_data, tuple) and len(table_data) >= 1:
                        image_obj = table_data[0]
                    if len(table) >= 2:
                        positions = table[1]

                if image_obj is not None:
                    content = (table_content or "").strip() or "image"
                    if len(content) > 900:
                        content = content[:900].rstrip() + "..."
                    meta = {
                        **base_metadata,
                        "doc_type_kwd": "image",
                        "content_type": "image",
                        "table_index": i,
                        "image": image_obj,
                    }
                    if positions is not None:
                        meta["positions"] = positions
                    documents.append(Document(page_content=content, metadata=meta))
            except Exception as exc:
                # Best-effort: never fail parsing due to table image handling.
                self._logger.debug("Failed to attach table image metadata; continuing parse: %s", exc)

        return documents

    def _extract_table_content(self, table: Any) -> str:
        """
        Extract content from table data.

        Args:
            table: Table data (may be in different formats).

        Returns:
            Table content string.
        """
        if isinstance(table, tuple) and len(table) >= 1:
            table_data = table[0]
            if isinstance(table_data, tuple) and len(table_data) >= 2:
                # (image, html) format
                html_content = table_data[1]
                if isinstance(html_content, str):
                    return html_content
                elif isinstance(html_content, list):
                    return "\n".join(str(x) for x in html_content)
                return html_content if html_content else ""
            elif isinstance(table_data, str):
                return table_data
        return str(table)

    def parse(
        self,
        file_path: Path,
        **kwargs
    ) -> list[Document]:
        """
        Parse document.

        Args:
            file_path: Document file path.
            **kwargs: Extra args.

        Returns:
            List of LangChain Documents.
        """
        file_path = Path(file_path)
        self._validate_file(file_path)

        parser = self._get_parser()

        # Check installation.
        ok, reason = self._check_parser_installation(parser)
        if not ok:
            raise RuntimeError(f"{self._get_parser_name()} not available: {reason}")

        # Call underlying parser.
        callback = self._create_callback()
        sections, tables = self._call_parse_method(
            parser=parser,
            file_path=file_path,
            binary=None,
            callback=callback,
            **kwargs
        )

        # Convert to LangChain Document format.
        base_metadata = {
            "source": str(file_path.name),
            "filename": file_path.name,
            "file_type": file_path.suffix.lstrip(".").lower(),
            "parser": self._get_parser_name(),
        }

        documents = []
        documents.extend(self._convert_sections_to_documents(sections, base_metadata))
        documents.extend(self._convert_tables_to_documents(tables, base_metadata))

        self._logger.info(
            f"{self._get_parser_name()} parsed {file_path.name}: {len(documents)} documents"
        )
        return documents

    async def aparse(
        self,
        file_path: Path,
        **kwargs,
    ) -> list[Document]:
        """
        Parse document asynchronously.

        Args:
            file_path: Document file path.
            **kwargs: Extra args.

        Returns:
            List of LangChain Documents.
        """
        file_path = Path(file_path)
        self._validate_file(file_path)

        parser = self._get_parser()

        # Check installation.
        ok, reason = self._check_parser_installation(parser)
        if not ok:
            raise RuntimeError(f"{self._get_parser_name()} not available: {reason}")

        # Call underlying parser in a thread pool (parser may be sync).
        def _parse_in_thread():
            callback = self._create_callback()
            sections, tables = self._call_parse_method(
                parser=parser,
                file_path=file_path,
                binary=None,
                callback=callback,
                **kwargs
            )

            # Convert to LangChain Document format.
            base_metadata = {
                "source": str(file_path.name),
                "filename": file_path.name,
                "file_type": file_path.suffix.lstrip(".").lower(),
                "parser": self._get_parser_name(),
            }

            documents = []
            documents.extend(self._convert_sections_to_documents(sections, base_metadata))
            documents.extend(self._convert_tables_to_documents(tables, base_metadata))

            return documents

        documents = await asyncio.to_thread(_parse_in_thread)

        self._logger.info(
            f"{self._get_parser_name()} parsed {file_path.name}: {len(documents)} documents"
        )
        return documents
