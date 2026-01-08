"""
Advanced parser base class.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, List, Optional, Set, Tuple

from langchain_core.documents import Document


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
    SUPPORTED_EXTENSIONS: Optional[Set[str]] = None

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
    def _check_parser_installation(self, parser: Any) -> Tuple[bool, str]:
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
        binary: bytes,
        callback: Callable[[float, str], None],
        **kwargs
    ) -> Tuple[List, List]:
        """
        Call the underlying parser's parse method.

        Args:
            parser: Underlying parser instance.
            file_path: File path.
            binary: File bytes.
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
        sections: List,
        base_metadata: dict
    ) -> List[Document]:
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

        text_parts = []
        for section in sections:
            if isinstance(section, tuple):
                text = section[0] if section[0] else ""
            else:
                text = str(section)
            if text.strip():
                text_parts.append(text.strip())

        if not text_parts:
            return []

        return [Document(
            page_content="\n\n".join(text_parts),
            metadata={**base_metadata, "content_type": "text"}
        )]

    def _convert_tables_to_documents(
        self,
        tables: List,
        base_metadata: dict
    ) -> List[Document]:
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
    ) -> List[Document]:
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

        # Read file.
        with open(file_path, "rb") as f:
            binary = f.read()

        # Call underlying parser.
        callback = self._create_callback()
        sections, tables = self._call_parse_method(
            parser=parser,
            file_path=file_path,
            binary=binary,
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
    ) -> List[Document]:
        """
        Parse document asynchronously (aiofiles for async file IO).

        Args:
            file_path: Document file path.
            **kwargs: Extra args.

        Returns:
            List of LangChain Documents.
        """
        import aiofiles
        
        file_path = Path(file_path)
        self._validate_file(file_path)

        parser = self._get_parser()

        # Check installation.
        ok, reason = self._check_parser_installation(parser)
        if not ok:
            raise RuntimeError(f"{self._get_parser_name()} not available: {reason}")

        # Read file asynchronously.
        async with aiofiles.open(file_path, "rb") as f:
            binary = await f.read()

        # Call underlying parser in a thread pool (parser may be sync).
        def _parse_in_thread():
            callback = self._create_callback()
            sections, tables = self._call_parse_method(
                parser=parser,
                file_path=file_path,
                binary=binary,
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
