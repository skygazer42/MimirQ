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

# JSON splitting incorporates LangChain's recursive JSON splitter adapted by InfiniFlow.
# https://github.com/langchain-ai/langchain/blob/master/libs/text-splitters/langchain_text_splitters/json.py

"""
JSON parser (fallback / lightweight).

Provides a robust JSON/JSONL parser that returns pretty-printed JSON text and
basic structural metadata. This is useful as a fallback when MarkItDown is not
available or fails.
"""

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.rag.ingestion.parsing.utils.text import read_text_file, read_text_source


def _try_parse_jsonl(raw: str) -> list[Any] | None:
    items: list[Any] = []
    total = 0
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        total += 1
        try:
            items.append(json.loads(stripped))
        except json.JSONDecodeError:
            # Preserve the complete raw source when any record is invalid.
            logging.getLogger(__name__).debug("Invalid JSONL record; preserving raw source", exc_info=True)
            return None
    if total >= 2:
        return items
    return None


class JsonParser:
    """Parse JSON / JSONL into a chunk-friendly text representation."""

    def __init__(self, max_chunk_size: int = 2000, min_chunk_size: int | None = None):
        super().__init__()
        self.max_chunk_size = max_chunk_size * 2
        self.min_chunk_size = min_chunk_size if min_chunk_size is not None else max(max_chunk_size - 200, 50)

    def parse(self, file_path: Path) -> list[Document]:
        decoded = read_text_file(file_path)
        raw = decoded.text

        data: Any = None
        json_valid = False
        json_mode = "json"

        stripped = raw.strip()
        if stripped:
            try:
                data = json.loads(stripped)
                json_valid = True
            except json.JSONDecodeError:
                # Try JSONL as a fallback.
                jsonl = _try_parse_jsonl(stripped)
                if jsonl is not None:
                    data = jsonl
                    json_valid = True
                    json_mode = "jsonl"

        if json_valid:
            content = json.dumps(data, ensure_ascii=False, indent=2)
        else:
            content = raw

        metadata: dict[str, Any] = {
            "source": str(file_path.name),
            "file_type": "json",
            "json_valid": json_valid,
            "json_mode": json_mode,
            "encoding": decoded.encoding,
            "encoding_confidence": decoded.confidence,
            "encoding_had_bom": decoded.had_bom,
        }

        if json_valid:
            if isinstance(data, list):
                metadata["json_top_level"] = "array"
                metadata["json_items"] = len(data)
            elif isinstance(data, dict):
                metadata["json_top_level"] = "object"
                metadata["json_keys"] = list(data.keys())[:200]
            else:
                metadata["json_top_level"] = type(data).__name__

        return [Document(page_content=content, metadata=metadata)]

    def split_bytes(self, binary: bytes) -> list[str]:
        json_data = json.loads(read_text_source(fnm="", binary=binary))
        chunks = self.split_json(json_data, True)
        sections = [json.dumps(line, ensure_ascii=False) for line in chunks]
        return sections

    @staticmethod
    def _json_size(data: dict) -> int:
        """Calculate the size of the serialized JSON object."""
        return len(json.dumps(data, ensure_ascii=False))

    @staticmethod
    def _set_nested_dict(d: dict, path: list[str], value: Any) -> None:
        """Set a value in a nested dictionary based on the given path."""
        for key in path[:-1]:
            d = d.setdefault(key, {})
        d[path[-1]] = value

    def _list_to_dict_preprocessing(self, data: Any) -> Any:
        if isinstance(data, dict):
            # Process each key-value pair in the dictionary
            return {k: self._list_to_dict_preprocessing(v) for k, v in data.items()}
        elif isinstance(data, list):
            # Convert the list to a dictionary with index-based keys
            return {str(i): self._list_to_dict_preprocessing(item) for i, item in enumerate(data)}
        else:
            # Base case: the item is neither a dict nor a list, so return it unchanged
            return data

    def _json_split(
        self,
        data,
        current_path: list[str] | None,
        chunks: list[dict] | None,
    ) -> list[dict]:
        """
        Split json into maximum size dictionaries while preserving structure.
        """
        current_path = [] if current_path is None else current_path
        chunks = [{}] if chunks is None else chunks
        if isinstance(data, dict):
            for key, value in data.items():
                new_path = current_path + [key]
                chunk_size = self._json_size(chunks[-1])
                size = self._json_size({key: value})
                remaining = self.max_chunk_size - chunk_size

                if size < remaining:
                    # Add item to current chunk
                    self._set_nested_dict(chunks[-1], new_path, value)
                else:
                    if chunk_size >= self.min_chunk_size:
                        # Chunk is big enough, start a new chunk
                        chunks.append({})

                    # Iterate
                    self._json_split(value, new_path, chunks)
        else:
            # handle single item
            self._set_nested_dict(chunks[-1], current_path, data)
        return chunks

    def split_json(
        self,
        json_data,
        convert_lists: bool = False,
    ) -> list[Any]:
        """Splits JSON into a list of JSON chunks"""

        if (
            not isinstance(json_data, (dict, list))
            or not json_data
            or isinstance(json_data, list)
            and not convert_lists
        ):
            return [json_data]
        if convert_lists:
            preprocessed_data = self._list_to_dict_preprocessing(json_data)
            chunks = self._json_split(preprocessed_data, None, None)
        else:
            chunks = self._json_split(json_data, None, None)

        # Remove the last chunk if it's empty
        if len(chunks) > 1 and not chunks[-1]:
            chunks.pop()
        return chunks

    def split_text(
        self,
        json_data: dict[str, Any],
        convert_lists: bool = False,
        ensure_ascii: bool = True,
    ) -> list[str]:
        """Splits JSON into a list of JSON formatted strings"""

        chunks = self.split_json(json_data=json_data, convert_lists=convert_lists)

        # Convert to string
        return [json.dumps(chunk, ensure_ascii=ensure_ascii) for chunk in chunks]
