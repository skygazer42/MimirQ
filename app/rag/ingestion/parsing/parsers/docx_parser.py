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
DOCX parser (fallback / lightweight).

Used as a best-effort fallback when MarkItDown is unavailable or fails.
Relies on python-docx (pure Python) to extract paragraphs and tables.
"""

import logging
import re
from collections import Counter
from contextlib import closing
from functools import reduce
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.rag.ingestion.parsing.utils.markdown_table import build_markdown_table, clean_table_cell, infer_table_header

_HEADING_LEVEL_RE = re.compile(r"(\d+)")


def _looks_like_heading_style(style_name: str) -> bool:
    s = (style_name).strip()
    if not s:
        return False
    # Common styles: "Heading 1", "Heading 2", "标题 1", ...
    s_lower = s.lower()
    return s_lower.startswith("heading") or "标题" in s


def _heading_level(style_name: str) -> int:
    raw = (style_name).strip()
    m = _HEADING_LEVEL_RE.search(raw)
    if not m:
        return 2
    try:
        lvl = int(m.group(1))
    except ValueError:
        return 2
    return max(1, min(6, lvl))


def _is_list_paragraph(p) -> bool:  # noqa: ANN001
    """
    Best-effort list detection for python-docx.

    We avoid resolving numbering definitions; for chunking, stable indentation + list markers
    are more important than exact numbering.
    """
    ppr = p._p.pPr  # noqa: SLF001
    return ppr is not None and ppr.numPr is not None


def _list_level(p) -> int:  # noqa: ANN001
    from docx.oxml.exceptions import InvalidXmlError

    ppr = p._p.pPr  # noqa: SLF001
    num_pr = ppr.numPr if ppr is not None else None
    ilvl = num_pr.ilvl if num_pr is not None else None
    if ilvl is None:
        return 0
    try:
        return max(0, ilvl.val)
    except (InvalidXmlError, ValueError):
        return 0


def _list_marker(style_name: str) -> str:
    s = (style_name).strip().lower()
    # Keep ordered lists recognizable; exact numbering is not required.
    if "number" in s or "编号" in s or "序号" in s:
        return "1."
    return "-"


def _iter_docx_blocks(doc):  # noqa: ANN001
    """
    Yield paragraph/table blocks in document order.

    python-docx exposes paragraphs and tables separately; to preserve reading order
    we iterate the underlying XML body children.
    """
    from docx.oxml.table import CT_Tbl  # type: ignore
    from docx.oxml.text.paragraph import CT_P  # type: ignore
    from docx.table import Table  # type: ignore
    from docx.text.paragraph import Paragraph  # type: ignore

    body = doc.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield Table(child, doc)


def _render_paragraph_block(block) -> str | None:  # noqa: ANN001
    text = block.text.strip()
    if not text:
        return None

    style = getattr(block, "style", None)
    style_name = str(getattr(style, "name", "") or "")

    if _looks_like_heading_style(style_name):
        level = _heading_level(style_name)
        return f"{'#' * level} {text}"

    if _is_list_paragraph(block):
        lvl = _list_level(block)
        indent = "  " * min(6, lvl)
        marker = _list_marker(style_name)
        return f"{indent}{marker} {text}"

    return text


def _render_table_block(block) -> str | None:  # noqa: ANN001
    rows: list[list[str]] = []
    for row in block.rows:
        cells: list[str] = []
        for cell in row.cells:
            cells.append(clean_table_cell(cell.text))
        rows.append(cells)

    if not rows:
        return None

    header, body = infer_table_header(rows)
    return build_markdown_table(header=header, rows=body)


def _render_docx_block(block) -> str | None:  # noqa: ANN001
    if hasattr(block, "text") and hasattr(block, "style"):
        return _render_paragraph_block(block)
    if hasattr(block, "rows"):
        return _render_table_block(block)
    return None


_DOCX_HEADING_RE = re.compile(r"Heading\s*(\d+)", re.I)
_CORRUPTED_IMAGE_LOG = "The recognized image stream appears to be corrupted. Skipping image."


def _load_docx_document(source: str | bytes):
    from docx import Document as DocxDocument

    if isinstance(source, str):
        return DocxDocument(source)
    with BytesIO(source) as buffer:
        return DocxDocument(buffer)


def _paragraph_style_name(paragraph):
    style = getattr(paragraph, "style", None)
    return getattr(style, "name", "") or ""


def _concat_owned_docx_images(left, right, *, owned_images: dict[int, Any]):
    from app.rag.ingestion.parsing.enrich.image_understanding import concat_images

    image = concat_images(left, right)
    if image is not None:
        owned_images[id(image)] = image
    return image


def _close_unreturned_docx_images(owned_images: dict[int, Any], retained: set[int]) -> None:
    for image_id, image in owned_images.items():
        if image_id not in retained:
            image.close()


def _load_docx_relationships(baseURI, rels_item_xml):  # noqa: N803 - python-docx loader protocol
    """
    Return |_SerializedRelationships| instance loaded with the
    relationships contained in *rels_item_xml*. Returns an empty
    collection if *rels_item_xml* is |None|.
    """
    from docx.opc.oxml import parse_xml
    from docx.opc.pkgreader import _SerializedRelationship, _SerializedRelationships

    srels = _SerializedRelationships()
    if rels_item_xml is not None:
        rels_elm = parse_xml(rels_item_xml)
        for rel_elm in rels_elm.Relationship_lst:
            if rel_elm.target_ref in ("../NULL", "NULL"):
                continue
            srels._srels.append(_SerializedRelationship(baseURI, rel_elm))
    return srels


def _table_block_type(block):
    from app.rag.ingestion.parsing.utils import tokenizer as rag_tokenizer

    patterns = [
        ("^(20|19)\\d{2}[年/-]\\d{1,2}[月/-]\\d{1,2}日*$", "Dt"),
        (r"^(20|19)\d{2}年$", "Dt"),
        (r"^(20|19)\d{2}[年/-]\d{1,2}月*$", "Dt"),
        ("^\\d{1,2}[月/-]\\d{1,2}日*$", "Dt"),
        (r"^第*[一二三四1-4]季度$", "Dt"),
        (r"^(20|19)\d{2}年*[一二三四1-4]季度$", "Dt"),
        (r"^(20|19)\d{2}[ABCDE]$", "DT"),
        ("^[0-9.,+%/ -]+$", "Nu"),
        (r"^[0-9A-Z/\._~-]+$", "Ca"),
        (r"^[A-Z]*[a-z' -]+$", "En"),
        (r"^[0-9.,+-]+[0-9A-Za-z/$￥%<>（）()' -]+$", "NE"),
        (r"^.{1}$", "Sg"),
    ]
    for pattern, name in patterns:
        if re.search(pattern, block):
            return name

    tokens = [token for token in rag_tokenizer.tokenize(block).split() if len(token) > 1]
    if len(tokens) > 3:
        return "Tx" if len(tokens) < 12 else "Lx"
    if len(tokens) == 1 and rag_tokenizer.tag(tokens[0]) == "nr":
        return "Nr"
    return "Ot"


def _dominant_table_type(df):
    block_types = [
        _table_block_type(str(df.iloc[row, column]))
        for row in range(1, len(df))
        for column in range(len(df.iloc[row, :]))
    ]
    return max(Counter(block_types).items(), key=lambda item: item[1])[0]


def _header_rows(df, dominant_type):
    header_rows = [0]
    if dominant_type != "Nu":
        return header_rows
    for row in range(1, len(df)):
        row_types = Counter(_table_block_type(str(df.iloc[row, column])) for column in range(len(df.iloc[row, :])))
        if max(row_types.items(), key=lambda item: item[1])[0] != dominant_type:
            header_rows.append(row)
    return header_rows


def _active_header_offsets(header_rows, row_index):
    header_offsets = [header_row - row_index for header_row in header_rows]
    header_offsets = [offset for offset in header_offsets if offset < 0]
    index = len(header_offsets) - 1
    while index > 0:
        if header_offsets[index] - header_offsets[index - 1] > 1:
            return header_offsets[index:]
        index -= 1
    return header_offsets


def _header_prefixes(df, row_index, header_offsets):
    headers = []
    for column in range(len(df.iloc[row_index, :])):
        values = []
        for offset in header_offsets:
            value = str(df.iloc[row_index + offset, column]).strip()
            if value in values:
                continue
            values.append(value)
        header = ",".join(values)
        headers.append(f"{header}: " if header else "")
    return headers


def _compose_table_row(df, row_index, header_rows):
    header_offsets = _active_header_offsets(header_rows, row_index)
    headers = _header_prefixes(df, row_index, header_offsets)
    cells = []
    for column in range(len(df.iloc[row_index, :])):
        cell = str(df.iloc[row_index, column])
        if not cell:
            continue
        cells.append(headers[column] + cell)
    return ";".join(cells)


class DocxParser:
    """Parse DOCX into a chunk-friendly plain text representation."""

    def parse(self, file_path: Path) -> list[Document]:
        doc = _load_docx_document(str(file_path))

        parts: list[str] = []
        for block in _iter_docx_blocks(doc):
            rendered = _render_docx_block(block)
            if rendered:
                parts.append(rendered)

        content = "\n\n".join(parts)
        metadata = {
            "source": str(file_path.name),
            "file_type": "docx",
        }
        return [Document(page_content=content, metadata=metadata)]

    def __extract_table_content(self, tb):
        import pandas as pd

        df = []
        for row in tb.rows:
            df.append([c.text for c in row.cells])
        return self.__compose_table_content(pd.DataFrame(df))

    def __compose_table_content(self, df):
        if len(df) < 2:
            return []
        max_type = _dominant_table_type(df)
        colnm = len(df.iloc[0, :])
        hdrows = _header_rows(df, max_type)
        lines = []
        for i in range(1, len(df)):
            if i in hdrows:
                continue
            lines.append(_compose_table_row(df, i, hdrows))

        if colnm > 3:
            return lines
        return ["\n".join(lines)]

    def parse_sections(self, source: str | bytes, from_page=0, to_page=100000000):
        self.doc = _load_docx_document(source)
        pn = 0  # parsed page
        secs = []  # parsed contents
        for p in self.doc.paragraphs:
            if pn > to_page:
                break

            runs_within_single_paragraph = []  # save runs within the range of pages
            for run in p.runs:
                if pn > to_page:
                    break
                if from_page <= pn < to_page and p.text.strip():
                    runs_within_single_paragraph.append(run.text)  # append run.text first

                # wrap page break checker into a static method
                if "lastRenderedPageBreak" in run._element.xml:
                    pn += 1

            secs.append(
                ("".join(runs_within_single_paragraph), p.style.name if hasattr(p.style, "name") else "")
            )  # then concat run.text as part of the paragraph

        tbls = [self.__extract_table_content(tb) for tb in self.doc.tables]
        return secs, tbls

    @staticmethod
    def _load_related_image_blob(document, embed):
        from docx.image.exceptions import InvalidImageStreamError, UnexpectedEndOfFileError, UnrecognizedImageError

        try:
            related_part = document.part.related_parts[embed]
            return related_part.image.blob
        except UnrecognizedImageError:
            logging.info("Unrecognized image format. Skipping image.")
        except UnexpectedEndOfFileError:
            logging.info("EOF was unexpectedly encountered while reading an image stream. Skipping image.")
        except (InvalidImageStreamError, UnicodeDecodeError):
            logging.info(_CORRUPTED_IMAGE_LOG)
        except Exception:
            logging.info(_CORRUPTED_IMAGE_LOG)
        return None

    @staticmethod
    def _image_from_blob(image_blob):
        from PIL import Image

        try:
            with BytesIO(image_blob) as buffer, closing(Image.open(buffer)) as image:
                return image.convert("RGB")
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            return None

    @staticmethod
    def _collect_blocks(doc):
        from docx.text.paragraph import Paragraph

        blocks = []
        try:
            for index, block in enumerate(doc._element.body):
                if block.tag.endswith("p"):
                    blocks.append(("p", index, Paragraph(block, doc)))
                elif block.tag.endswith("tbl"):
                    blocks.append(("t", index, None))
        except Exception as exc:
            logging.error("Error collecting blocks: %s", exc)
            return None
        return blocks

    @staticmethod
    def _find_table_position(blocks, table_index):
        table_count = 0
        for block_type, pos, _ in blocks:
            if block_type != "t":
                continue
            if table_count == table_index:
                return pos
            table_count += 1
        return -1

    @staticmethod
    def _heading_from_paragraph(paragraph):
        style_name = _paragraph_style_name(paragraph)
        match = _DOCX_HEADING_RE.search(style_name)
        if match is None:
            return None
        try:
            level = int(match.group(1))
        except Exception as exc:
            logging.error("Error parsing heading level: %s", exc)
            return None
        if level > 7:
            return None
        title_text = paragraph.text.strip()
        if not title_text:
            return None
        return level, title_text

    @staticmethod
    def _heading_hierarchy(blocks, target_table_pos):
        titles = []
        current_level = None
        for block_type, pos, block in reversed(blocks):
            if pos >= target_table_pos or block_type != "p":
                continue
            heading = DocxParser._heading_from_paragraph(block)
            if heading is None:
                continue
            level, title_text = heading
            if current_level is None or level < current_level:
                titles.append((level, title_text))
                current_level = level
                if level == 1:
                    break
        return sorted(titles, key=lambda item: item[0])

    @staticmethod
    def _consume_caption_image(lines, last_image):
        former_image = None
        if lines and lines[-1][1] and lines[-1][2] != "Caption":
            former_image = lines[-1][1].pop()
        elif last_image:
            former_image = last_image
            last_image = None
        return former_image, last_image

    @staticmethod
    def _page_break_count(paragraph):
        count = 0
        for run in paragraph.runs:
            run_xml = run._element.xml
            if "lastRenderedPageBreak" in run_xml:
                count += 1
                continue
            if "w:br" in run_xml and 'type="page"' in run_xml:
                count += 1
        return count

    @staticmethod
    def _row_to_html(row):
        html = "<tr>"
        cell_index = 0
        while cell_index < len(row.cells):
            span = 1
            cell = row.cells[cell_index]
            for sibling_index in range(cell_index + 1, len(row.cells)):
                if cell._tc is not row.cells[sibling_index]._tc:
                    break
                span += 1
                cell_index = sibling_index
            cell_index += 1
            if span == 1:
                html += f"<td>{escape(cell.text)}</td>"
            else:
                html += f"<td colspan='{span}'>{escape(cell.text)}</td>"
        return f"{html}</tr>"

    def _process_paragraph(self, lines, last_image, paragraph, owned_images):
        if paragraph.text.strip():
            style_name = _paragraph_style_name(paragraph)
            if style_name == "Caption":
                former_image, last_image = self._consume_caption_image(lines, last_image)
                lines.append((self.__clean(paragraph.text), [former_image], style_name))
                return last_image

            current_image = self.get_picture(self.doc, paragraph)
            if current_image is not None:
                owned_images[id(current_image)] = current_image
            image_list = [current_image]
            if last_image:
                image_list.insert(0, last_image)
                last_image = None
            lines.append((self.__clean(paragraph.text), image_list, style_name))
            return last_image

        current_image = self.get_picture(self.doc, paragraph)
        if current_image is not None:
            owned_images[id(current_image)] = current_image
        if current_image:
            if lines:
                lines[-1][1].append(current_image)
            else:
                last_image = current_image
        return last_image

    def get_picture(self, document, paragraph):
        imgs = paragraph._element.xpath(".//pic:pic")
        if not imgs:
            return None
        res_img = None
        owned_images: dict[int, Any] = {}
        retained: set[int] = set()
        try:
            for img in imgs:
                embed = img.xpath(".//a:blip/@r:embed")
                if not embed:
                    continue
                image_blob = self._load_related_image_blob(document, embed[0])
                if image_blob is None:
                    continue
                image = self._image_from_blob(image_blob)
                if image is None:
                    continue
                owned_images[id(image)] = image
                res_img = _concat_owned_docx_images(res_img, image, owned_images=owned_images)
            if res_img is not None:
                retained.add(id(res_img))
            return res_img
        finally:
            _close_unreturned_docx_images(owned_images, retained)

    def __clean(self, line):
        line = re.sub(r"\u3000", " ", line).strip()
        return line

    def __get_nearest_title(self, table_index, filename):
        """Get the hierarchical title structure before the table"""
        doc_name = re.sub(r"\.[a-zA-Z]+$", "", filename)
        if not doc_name:
            doc_name = "Untitled Document"
        blocks = self._collect_blocks(self.doc)
        if blocks is None:
            return ""
        target_table_pos = self._find_table_position(blocks, table_index)
        if target_table_pos == -1:
            return ""
        titles = self._heading_hierarchy(blocks, target_table_pos)
        if titles:
            hierarchy = [doc_name] + [title for _, title in titles]
            return " > ".join(hierarchy)
        return ""

    def parse_media(self, filename, binary=None, from_page=0, to_page=100000):
        from docx.opc.pkgreader import _SerializedRelationships

        _SerializedRelationships.load_from_xml = _load_docx_relationships
        self.doc = _load_docx_document(filename if binary is None else binary)
        pn = 0
        lines = []
        last_image = None
        owned_images: dict[int, Any] = {}
        retained: set[int] = set()
        try:
            for paragraph in self.doc.paragraphs:
                if pn > to_page:
                    break
                if from_page <= pn < to_page:
                    last_image = self._process_paragraph(lines, last_image, paragraph, owned_images)
                pn += self._page_break_count(paragraph)
            if last_image is not None:
                lines.append(("", [last_image], ""))
            new_line = [
                (
                    line[0],
                    reduce(
                        lambda left, right: _concat_owned_docx_images(left, right, owned_images=owned_images), line[1]
                    )
                    if line[1]
                    else None,
                )
                for line in lines
            ]

            tbls = []
            for index, table in enumerate(self.doc.tables):
                title = self.__get_nearest_title(index, filename)
                html = "<table>"
                if title:
                    html += f"<caption>Table Location: {escape(title)}</caption>"
                for row in table.rows:
                    html += self._row_to_html(row)
                html += "</table>"
                tbls.append(((None, html), ""))
            retained = {id(image) for _text, image in new_line if image is not None}
            return new_line, tbls
        finally:
            _close_unreturned_docx_images(owned_images, retained)
