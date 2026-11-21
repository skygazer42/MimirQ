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
Text / Markdown parsers.
"""

import re
from pathlib import Path

from langchain_core.documents import Document

from app.infrastructure.tokens import num_tokens_from_string
from app.rag.ingestion.parsing.utils.text import read_text_file, read_text_source


class TextParser:
    """Plain text parser."""

    def parse(self, file_path: Path) -> list[Document]:
        """
        Parse a plain text file into Document list.
        """
        decoded = read_text_file(file_path)
        content = decoded.text

        file_type = file_path.suffix.lstrip(".").lower() or "txt"
        metadata = {
            "source": str(file_path.name),
            "file_type": file_type,
            "encoding": decoded.encoding,
            "encoding_confidence": decoded.confidence,
            "encoding_had_bom": decoded.had_bom,
        }

        return [Document(page_content=content, metadata=metadata)]


class MarkdownParser:
    """Markdown parser."""

    def parse(self, file_path: Path) -> list[Document]:
        """
        Parse a Markdown file into Document list.
        Preserves raw Markdown text (better for RAG).
        """
        decoded = read_text_file(file_path)
        md_content = decoded.text

        metadata = {
            "source": str(file_path.name),
            "file_type": "md",
            "encoding": decoded.encoding,
            "encoding_confidence": decoded.confidence,
            "encoding_had_bom": decoded.had_bom,
        }

        return [Document(page_content=md_content, metadata=metadata)]


def split_text_sections(txt: str, chunk_token_num: int = 128, delimiter: str = "\n!?;。；！？") -> list[list[str]]:
    if not isinstance(txt, str):
        raise TypeError("txt type should be str!")
    cks = [""]
    tk_nums = [0]
    delimiter = delimiter.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")

    def add_chunk(t):
        nonlocal cks, tk_nums, delimiter
        tnum = num_tokens_from_string(t)
        if tk_nums[-1] > chunk_token_num:
            cks.append(t)
            tk_nums.append(tnum)
        else:
            cks[-1] += t
            tk_nums[-1] += tnum

    dels = []
    s = 0
    for m in re.finditer(r"`([^`]+)`", delimiter, re.I):
        f, t = m.span()
        dels.append(m.group(1))
        dels.extend(list(delimiter[s:f]))
        s = t
    if s < len(delimiter):
        dels.extend(list(delimiter[s:]))
    dels = [re.escape(d) for d in dels if d]
    dels = [d for d in dels if d]
    dels = "|".join(dels)
    secs = re.split(r"(%s)" % dels, txt)
    for sec in secs:
        if re.match(f"^{dels}$", sec):
            continue
        add_chunk(sec)

    return [[c, ""] for c in cks]


def parse_text_sections(
    filename: str,
    binary: bytes | None = None,
    chunk_token_num: int = 128,
    delimiter: str = "\n!?;。；！？",
) -> list[list[str]]:
    return split_text_sections(read_text_source(filename, binary), chunk_token_num, delimiter)


def extract_markdown_tables_and_remainder(markdown_text: str, separate_tables: bool = True) -> tuple[str, list[str]]:
    if not bool(separate_tables):
        return markdown_text, []

    remainder, tables = _extract_markdown_tables(markdown_text)
    remainder, html_tables = _extract_html_tables(remainder)
    tables.extend(html_tables)
    return remainder, tables


def _is_table_separator(line):
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) < 2:
        return False
    return all(cell and set(cell) <= {"-", ":", " "} and cell.count("-") >= 3 for cell in cells)


def _extract_markdown_tables(markdown_text):
    if "|" not in markdown_text:
        return markdown_text, []
    lines = markdown_text.splitlines(keepends=True)
    tables = []
    remainder = []
    index = 0
    while index < len(lines):
        if index + 1 < len(lines) and "|" in lines[index] and _is_table_separator(lines[index + 1]):
            start = index
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                index += 1
            if index - start >= 3:
                tables.append("".join(lines[start:index]))
                continue
            remainder.extend(lines[start:index])
            continue
        remainder.append(lines[index])
        index += 1
    return "".join(remainder), tables


def _extract_html_tables(markdown_text):
    lowered = markdown_text.lower()
    if "<table" not in lowered:
        return markdown_text, []
    tables = []
    parts = []
    cursor = 0
    while True:
        start = lowered.find("<table", cursor)
        if start == -1:
            parts.append(markdown_text[cursor:])
            break
        end = lowered.find("</table>", start)
        if end == -1:
            parts.append(markdown_text[cursor:])
            break
        end += len("</table>")
        parts.append(markdown_text[cursor:start])
        tables.append(markdown_text[start:end])
        cursor = end
    return "".join(parts), tables
