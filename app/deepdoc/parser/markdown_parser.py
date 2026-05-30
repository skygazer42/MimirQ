# -*- coding: utf-8 -*-
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

class IntegratedPipelineMarkdownParser:
    def __init__(self, chunk_token_num=128):
        self.chunk_token_num = int(chunk_token_num)

    def extract_tables_and_remainder(self, markdown_text, separate_tables=True):
        if not bool(separate_tables):
            return markdown_text, []

        remainder, tables = self._extract_markdown_tables(markdown_text)
        remainder, html_tables = self._extract_html_tables(remainder)
        tables.extend(html_tables)
        return remainder, tables

    @staticmethod
    def _is_table_separator(line):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            return False
        return all(cell and set(cell) <= {"-", ":", " "} and cell.count("-") >= 3 for cell in cells)

    @classmethod
    def _extract_markdown_tables(cls, markdown_text):
        if "|" not in markdown_text:
            return markdown_text, []
        lines = markdown_text.splitlines(keepends=True)
        tables = []
        remainder = []
        index = 0
        while index < len(lines):
            if index + 1 < len(lines) and "|" in lines[index] and cls._is_table_separator(lines[index + 1]):
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

    @staticmethod
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
