"""
JSON and Code Text Splitters

Provides specialized splitters for JSON data and programming code.
"""

import ast
import json
import logging
import re
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.utils.source_lines import apply_splitter_span

logger = logging.getLogger("rag.chunking.strategies.json_code")

SEP_CLASS = "\nclass "
SEP_CONST = "\nconst "
SEP_IMPORT = "\nimport "
CLASS_NAME_RE = r"class\s+(\w+)"


class JSONChunker(BaseChunker):
    """
    JSON-aware chunker that respects JSON structure.

    Features:
    - Splits JSON arrays into individual elements
    - Preserves nested object integrity
    - Handles both compact and pretty-printed JSON
    - Maintains valid JSON in each chunk when possible
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 0,  # Usually 0 for JSON
        min_chunk_size: int = 200,
        max_depth: int | None = None,
    ) -> None:
        """
        Initialize the JSON chunker.

        Args:
            chunk_size: Maximum size of each chunk
            chunk_overlap: Overlap between chunks (usually 0 for JSON)
            min_chunk_size: Minimum chunk size before merging
            max_depth: Maximum depth to traverse for splitting
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        self.max_depth = max_depth

    def split_documents(self, documents: list[Document]) -> list[Document]:
        """Split documents containing JSON data."""
        all_chunks: list[Document] = []

        for doc in documents:
            text = doc.page_content
            original_metadata = dict(doc.metadata)

            if not text.strip():
                continue

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                logger.debug("Content is not valid JSON, using fallback splitter")
                all_chunks.extend(self._fallback_split(doc))
                continue

            all_chunks.extend(self._split_json(data, original_metadata))

        # Re-index chunks
        for idx, chunk in enumerate(all_chunks):
            chunk.metadata["chunk_index"] = idx

        return all_chunks

    def _split_json(
        self,
        data: Any,
        base_metadata: dict[str, Any],
        path: str = "$",
        depth: int = 0,
    ) -> list[Document]:
        """Recursively split JSON data."""
        if self.max_depth is not None and depth > self.max_depth:
            # Max depth reached, serialize as single chunk
            return [self._create_chunk(data, base_metadata, path)]

        if isinstance(data, list):
            return self._split_array(data, base_metadata, path, depth)
        if isinstance(data, dict):
            return self._split_object(data, base_metadata, path, depth)
        return [self._create_chunk(data, base_metadata, path)]

    def _split_array(
        self,
        arr: list[Any],
        base_metadata: dict[str, Any],
        path: str,
        depth: int,
    ) -> list[Document]:
        """Split a JSON array."""
        chunks: list[Document] = []

        # Check if entire array fits in one chunk
        arr_str = json.dumps(arr, ensure_ascii=False, indent=2)
        if len(arr_str) <= self.chunk_size:
            return [self._create_chunk(arr, base_metadata, path)]

        # Split into individual elements
        current_batch: list[Any] = []
        current_size = 2  # For "[]"

        for idx, item in enumerate(arr):
            item_str = json.dumps(item, ensure_ascii=False, indent=2)
            # A pretty-printed array indents every line of each item.
            item_size = len(item_str) + 2 * (item_str.count("\n") + 1) + 2

            if current_size + item_size > self.chunk_size and current_batch:
                # Flush current batch
                chunks.append(
                    self._create_chunk(
                        current_batch,
                        base_metadata,
                        f"{path}[{idx - len(current_batch)}:{idx}]",
                    )
                )
                current_batch = []
                current_size = 2

            if 2 + item_size > self.chunk_size:
                # Item itself is too large, split recursively
                sub_chunks = self._split_json(
                    item,
                    base_metadata,
                    f"{path}[{idx}]",
                    depth + 1,
                )
                chunks.extend(sub_chunks)
            else:
                current_batch.append(item)
                current_size += item_size

        if current_batch:
            chunks.append(
                self._create_chunk(
                    current_batch,
                    base_metadata,
                    f"{path}[{len(arr) - len(current_batch)}:{len(arr)}]",
                )
            )

        return chunks

    def _split_object(
        self,
        obj: dict[str, Any],
        base_metadata: dict[str, Any],
        path: str,
        depth: int,
    ) -> list[Document]:
        """Split a JSON object."""
        # Check if entire object fits in one chunk
        obj_str = json.dumps(obj, ensure_ascii=False, indent=2)
        if len(obj_str) <= self.chunk_size:
            return [self._create_chunk(obj, base_metadata, path)]

        chunks: list[Document] = []

        # Split by keys
        for key, value in obj.items():
            value_str = json.dumps(value, ensure_ascii=False, indent=2)

            if len(value_str) > self.chunk_size:
                # Value is too large, split recursively
                sub_chunks = self._split_json(
                    value,
                    base_metadata,
                    f"{path}.{key}",
                    depth + 1,
                )
                chunks.extend(sub_chunks)
            else:
                # Create chunk for this key-value pair
                chunks.append(
                    self._create_chunk(
                        {key: value},
                        base_metadata,
                        f"{path}.{key}",
                    )
                )

        return chunks

    def _create_chunk(
        self,
        data: Any,
        base_metadata: dict[str, Any],
        json_path: str,
    ) -> Document:
        """Create a Document chunk from JSON data."""
        content = json.dumps(data, ensure_ascii=False, indent=2)

        metadata = {
            **base_metadata,
            "chunk_strategy": "json",
            "json_path": json_path,
            "content_type": "json",
            "start_char": None,
            "end_char": None,
            "offset_mapping_reason": "serialized_json_chunk",
        }

        return Document(page_content=content, metadata=metadata)

    def _fallback_split(self, doc: Document) -> list[Document]:
        """Fall back to recursive text splitting."""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ",", " ", ""],
            add_start_index=True,
        )

        chunks = splitter.split_documents([doc])

        for chunk in chunks:
            chunk.metadata["chunk_strategy"] = "json_fallback"
            start = chunk.metadata.pop("start_index", None)
            apply_splitter_span(chunk.metadata, start_index=start, content=chunk.page_content)

        return chunks


class CodeChunker(BaseChunker):
    """
    Code-aware chunker that respects programming language structure.

    Features:
    - Splits on function/class boundaries
    - Preserves docstrings with their functions
    - Language-specific separators
    - Maintains syntactic integrity
    """

    # Language-specific separators
    LANGUAGE_SEPARATORS = {
        "python": [
            SEP_CLASS,
            "\ndef ",
            "\n\tdef ",
            "\n    def ",
            "\nif __name__",
            "\n\n\n",
            "\n\n",
            "\n",
            " ",
            "",
        ],
        "javascript": [
            "\nfunction ",
            SEP_CONST,
            "\nlet ",
            "\nvar ",
            SEP_CLASS,
            "\nexport ",
            SEP_IMPORT,
            "\n\n",
            "\n",
            ";",
            " ",
            "",
        ],
        "typescript": [
            "\nfunction ",
            SEP_CONST,
            "\nlet ",
            SEP_CLASS,
            "\ninterface ",
            "\ntype ",
            "\nexport ",
            SEP_IMPORT,
            "\n\n",
            "\n",
            ";",
            " ",
            "",
        ],
        "java": [
            "\npublic class ",
            SEP_CLASS,
            "\npublic ",
            "\nprivate ",
            "\nprotected ",
            "\n@",
            "\n\n",
            "\n",
            ";",
            " ",
            "",
        ],
        "go": [
            "\nfunc ",
            "\ntype ",
            "\nvar ",
            SEP_CONST,
            "\npackage ",
            SEP_IMPORT,
            "\n\n",
            "\n",
            " ",
            "",
        ],
        "sql": [
            "\nSELECT ",
            "\nINSERT ",
            "\nUPDATE ",
            "\nDELETE ",
            "\nCREATE ",
            "\nALTER ",
            "\nDROP ",
            "\nWITH ",
            ";\n",
            ";",
            "\n",
            " ",
            "",
        ],
        "default": [
            "\n\n\n",
            "\n\n",
            "\n",
            " ",
            "",
        ],
    }

    # File extension to language mapping
    EXTENSION_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".go": "go",
        ".sql": "sql",
    }

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        language: str | None = None,
        preserve_functions: bool = True,
    ) -> None:
        """
        Initialize the code chunker.

        Args:
            chunk_size: Maximum chunk size
            chunk_overlap: Overlap between chunks
            language: Programming language (auto-detected if None)
            preserve_functions: Try to keep functions intact
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.language = language
        self.preserve_functions = preserve_functions

    def split_documents(self, documents: list[Document]) -> list[Document]:
        """Split code documents."""
        all_chunks: list[Document] = []

        for doc in documents:
            text = doc.page_content
            original_metadata = dict(doc.metadata)

            if not text.strip():
                continue

            # Detect language
            language = self._detect_language(doc)
            separators = self.LANGUAGE_SEPARATORS.get(language, self.LANGUAGE_SEPARATORS["default"])

            # Create language-specific splitter
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                separators=separators,
            )

            # Split the document and compute stable positions for citations/highlighting.
            split_texts = splitter.split_text(text)
            search_pos = 0
            for split_text in split_texts:
                if not (split_text).strip():
                    continue

                start_idx = text.find(split_text, search_pos)
                if start_idx >= 0:
                    end_idx = start_idx + len(split_text)
                    search_pos = max(end_idx - self.chunk_overlap, start_idx + 1)
                else:
                    start_idx = None
                    end_idx = None

                metadata = {
                    **original_metadata,
                    "chunk_strategy": "code",
                    "language": language,
                    "chunk_index": len(all_chunks),
                    "start_char": start_idx,
                    "end_char": end_idx,
                }
                if start_idx is None:
                    metadata["offset_mapping_error"] = "chunk_text_not_found_in_source"

                # Extract function/class context
                context = self._extract_code_context(split_text, language)
                if context:
                    metadata["code_context"] = context

                all_chunks.append(Document(page_content=split_text, metadata=metadata))

        return all_chunks

    def _detect_language(self, doc: Document) -> Any:
        """Use the configured language, raw metadata override, or content hints."""
        # Check explicit language
        if self.language:
            return self.language

        metadata = doc.metadata

        # Check metadata
        if "language" in metadata:
            return metadata["language"]

        # Check file extension
        source = metadata.get("source")
        if isinstance(source, str):
            for ext, lang in self.EXTENSION_MAP.items():
                if source.endswith(ext):
                    return lang

        # Try to detect from content
        text = doc.page_content
        return self._detect_language_from_content(text)

    def _detect_language_from_content(self, text: str) -> str:
        """Detect language from code content."""
        patterns = {
            "python": [r"\bdef\s+\w+\s*\(", r"\bclass\s+\w+:", r"\bimport\s+\w+"],
            "javascript": [r"\bfunction\s+\w+\s*\(", r"\bconst\s+\w+\s*=", r"\blet\s+\w+\s*="],
            "typescript": [r"\binterface\s+\w+", r"\btype\s+\w+\s*=", r":\s*\w+\s*[;=]"],
            "java": [r"\bpublic\s+class\s+", r"\bprivate\s+\w+\s+\w+", r"\@\w+"],
            "go": [r"\bfunc\s+\w+\s*\(", r"\bpackage\s+\w+", r"\btype\s+\w+\s+struct"],
            "sql": [r"\bSELECT\s+", r"\bFROM\s+", r"\bWHERE\s+"],
        }

        scores = {}
        for lang, pats in patterns.items():
            score = sum(1 for p in pats if re.search(p, text, re.IGNORECASE))
            scores[lang] = score

        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best

        return "default"

    def _extract_code_context(self, text: str, language: Any) -> str | None:
        """Extract a function/class name; unsupported languages have no context."""
        patterns = {
            "python": [
                r"^\s*def\s+(\w+)\s*\(",
                r"^\s*class\s+(\w+)",
                r"^\s*async\s+def\s+(\w+)\s*\(",
            ],
            "javascript": [
                r"function\s+(\w+)\s*\(",
                r"const\s+(\w+)\s*=\s*(?:async\s*)?\(",
                CLASS_NAME_RE,
            ],
            "typescript": [
                r"function\s+(\w+)\s*\(",
                r"const\s+(\w+)\s*=",
                CLASS_NAME_RE,
                r"interface\s+(\w+)",
            ],
            "java": [
                CLASS_NAME_RE,
                r"(?:public|private|protected)\s+\w+\s+(\w+)\s*\(",
            ],
            "go": [
                r"func\s+(\w+)\s*\(",
                r"type\s+(\w+)\s+struct",
            ],
        }

        lang_patterns = patterns.get(language, [])

        for pattern in lang_patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                return match.group(1)

        return None


class SmartCodeChunker(BaseChunker):
    """
    Advanced code chunker with AST-like awareness.

    For Python code, attempts to keep complete functions/classes together.
    """

    def __init__(
        self,
        chunk_size: int = 1500,
        chunk_overlap: int = 200,
        target_language: str = "python",
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.target_language = target_language

        self._base_chunker = CodeChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            language=target_language,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        """Split documents with smart code awareness."""
        if self.target_language != "python":
            # Fall back to regular code chunker for other languages
            return self._base_chunker.split_documents(documents)

        all_chunks: list[Document] = []

        for doc in documents:
            text = doc.page_content
            original_metadata = dict(doc.metadata)

            if not text.strip():
                continue

            # Try to split Python into logical units
            units = self._split_python_units(text)
            search_pos = 0

            for unit_text, unit_type, unit_name in units:
                if not unit_text.strip():
                    continue
                unit_start = text.find(unit_text, max(0, search_pos))
                if unit_start < 0:
                    raise ValueError("Python code unit text was not found in its source document")
                unit_end = min(len(text), unit_start + len(unit_text))
                search_pos = max(unit_end, unit_start + 1)

                if len(unit_text) <= self.chunk_size:
                    # Unit fits in one chunk
                    all_chunks.append(
                        Document(
                            page_content=unit_text,
                            metadata={
                                **original_metadata,
                                "chunk_strategy": "smart_code",
                                "language": "python",
                                "chunk_index": len(all_chunks),
                                "code_unit_type": unit_type,
                                "code_unit_name": unit_name,
                                "start_char": unit_start,
                                "end_char": unit_end,
                            },
                        )
                    )
                else:
                    # Split large unit
                    sub_chunks = self._base_chunker.split_documents(
                        [Document(page_content=unit_text, metadata=original_metadata)]
                    )
                    for sub in sub_chunks:
                        meta = dict(sub.metadata)
                        if meta["start_char"] is not None:
                            meta["start_char"] = unit_start + meta["start_char"]
                        if meta["end_char"] is not None:
                            meta["end_char"] = unit_start + meta["end_char"]
                        meta["chunk_strategy"] = "smart_code"
                        meta["language"] = "python"
                        meta["code_unit_type"] = unit_type
                        meta["code_unit_name"] = unit_name
                        meta["chunk_index"] = len(all_chunks)
                        all_chunks.append(Document(page_content=sub.page_content, metadata=meta))

        return all_chunks

    @staticmethod
    def _definition_starts(text: str) -> dict[int, tuple[str, str]] | None:
        try:
            module = ast.parse(text)
        except SyntaxError:
            return None

        starts: dict[int, tuple[str, str]] = {}
        for node in module.body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = min((decorator.lineno for decorator in node.decorator_list), default=node.lineno)
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            starts[start] = (kind, node.name)
        return starts

    @staticmethod
    def _fallback_definition(line: str) -> tuple[str, str] | None:
        if match := re.match(r"^class\s+(\w+)", line):
            return "class", match.group(1)
        if match := re.match(r"^(?:async\s+)?def\s+(\w+)", line):
            return "function", match.group(1)
        return None

    def _split_python_units(self, text: str) -> list[tuple[str, str, str]]:
        """Split Python code into logical units (functions, classes)."""
        units = []
        definitions = self._definition_starts(text)

        current_unit = []
        current_type = "module"
        current_name = "<module>"

        for number, line in enumerate(text.split("\n"), start=1):
            definition = definitions.get(number) if definitions is not None else self._fallback_definition(line)
            if definition is not None:
                # Save previous unit if exists
                if current_unit:
                    units.append(
                        (
                            "\n".join(current_unit),
                            current_type,
                            current_name,
                        )
                    )
                    current_unit = []

                current_type, current_name = definition

            current_unit.append(line)

        # Save last unit
        if current_unit:
            units.append(
                (
                    "\n".join(current_unit),
                    current_type,
                    current_name,
                )
            )

        return units
