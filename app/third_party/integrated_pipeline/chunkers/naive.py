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

import logging
import os
import re
from dataclasses import dataclass, field
from functools import reduce
from io import BytesIO
from timeit import default_timer as timer
from typing import Any

import httpx
from docx import Document
from docx.image.exceptions import InvalidImageStreamError, UnexpectedEndOfFileError, UnrecognizedImageError
from docx.opc.oxml import parse_xml
from docx.opc.pkgreader import _SerializedRelationship, _SerializedRelationships
from markdown import markdown
from PIL import Image

import app.deepdoc.parser as deepdoc_parser
from app.core.optional_deps import optional_import
from app.deepdoc.parser import (
    DocxParser,
    ExcelParser,
    HtmlParser,
    JsonParser,
    MarkdownParser,
    PdfParser,
    TxtParser,
)
from app.deepdoc.parser.figure_parser import (
    VisionFigureParser,
    vision_figure_parser_docx_wrapper,
    vision_figure_parser_pdf_wrapper,
)
from app.deepdoc.parser.pdf_parser import PlainParser, VisionParser
from app.rag.core.logging import get_logger
from app.third_party.integrated_pipeline.common.constants import LLMType
from app.third_party.integrated_pipeline.common.token_utils import num_tokens_from_string
from app.third_party.integrated_pipeline.nlp import (
    attach_media_context,
    concat_img,
    find_codec,
    naive_merge,
    naive_merge_docx,
    naive_merge_with_images,
    rag_tokenizer,
    tokenize_chunks,
    tokenize_chunks_with_images,
    tokenize_table,
)
from app.third_party.integrated_pipeline.stubs.file_utils import (
    extract_embed_file,
    extract_html,
    extract_links_from_docx,
    extract_links_from_pdf,
)
from app.third_party.integrated_pipeline.stubs.llm_service import LLMBundle

DEFAULT_PARSER_CONFIG = {
    "chunk_token_num": 512,
    "delimiter": "\n!?。；！？",
    "layout_recognize": "DeepDOC",
    "analyze_hyperlink": True,
}
DOCX_HEADING_RE = re.compile(r"Heading\s*(\d+)", re.I)
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
HTML_IMAGE_RE = re.compile(r'src=["\\\']([^"\\\'>\\s]+)', re.IGNORECASE)
CORRUPTED_IMAGE_LOG = "The recognized image stream appears to be corrupted. Skipping image."


@dataclass
class ChunkContext:
    filename: str
    binary: bytes | None
    from_page: int
    to_page: int
    lang: str
    callback: Any
    kwargs: dict[str, Any]
    parser_config: dict[str, Any]
    child_delimiters: str
    is_english: bool
    doc: dict[str, Any]
    is_root: bool
    table_context_size: int
    image_context_size: int


@dataclass
class ChunkBody:
    res: list[Any] = field(default_factory=list)
    sections: list[Any] = field(default_factory=list)
    pdf_parser: Any = None
    section_images: list[Any] | None = None
    url_sources: list[str] = field(default_factory=list)
    is_markdown: bool = False
    return_now: bool = False


def _parser_source(filename, binary):
    return filename if not binary else binary


def _load_plaintext_parser(callback=None, **kwargs):
    if kwargs.get("layout_recognizer", "") == "Plain Text":
        return PlainParser()

    layout_name = str(kwargs.get("layout_recognizer", "") or "").strip()
    try:
        vision_model = LLMBundle(
            str(kwargs.get("tenant_id", "") or ""),
            LLMType.IMAGE2TEXT,
            llm_name=layout_name,
            lang=kwargs.get("lang", "Chinese"),
        )
        return VisionParser(vision_model=vision_model, **kwargs)
    except Exception as exc:
        if callback:
            callback(
                -1,
                (f"Vision layout_recognizer '{layout_name}' unavailable; falling back to Plain Text. ({exc})"),
            )
        return PlainParser()


def _paragraph_style_name(paragraph):
    style = getattr(paragraph, "style", None)
    return getattr(style, "name", "") or ""


def _build_chunk_context(filename, binary, from_page, to_page, lang, callback, kwargs):
    parser_config = kwargs.get("parser_config")
    if parser_config is None:
        parser_config = dict(DEFAULT_PARSER_CONFIG)

    child_delimiters = re.findall(r"`([^`]+)`", parser_config.get("children_delimiter", ""))
    child_delimiters = sorted(set(child_delimiters), key=lambda item: -len(item))
    child_delimiters = "|".join(re.escape(item) for item in child_delimiters if item)
    doc = {
        "docnm_kwd": filename,
        "title_tks": rag_tokenizer.tokenize(re.sub(r"\.[a-zA-Z]+$", "", filename)),
    }
    doc["title_sm_tks"] = rag_tokenizer.fine_grained_tokenize(doc["title_tks"])
    return ChunkContext(
        filename=filename,
        binary=binary,
        from_page=from_page,
        to_page=to_page,
        lang=lang,
        callback=callback,
        kwargs=kwargs,
        parser_config=parser_config,
        child_delimiters=child_delimiters,
        is_english=lang.lower() == "english",
        doc=doc,
        is_root=kwargs.get("is_root", True),
        table_context_size=max(0, int(parser_config.get("table_context_size", 0) or 0)),
        image_context_size=max(0, int(parser_config.get("image_context_size", 0) or 0)),
    )


def _resolve_chunk_handler(filename):
    handlers = (
        (r"\.docx$", _handle_docx_file),
        (r"\.pdf$", _handle_pdf_file),
        (r"\.(csv|xlsx?)$", _handle_spreadsheet_file),
        (r"\.(txt|py|js|java|c|cpp|h|php|go|ts|sh|cs|kt|sql)$", _handle_text_file),
        (r"\.(md|markdown)$", _handle_markdown_file),
        (r"\.(htm|html)$", _handle_html_file),
        (r"\.(json|jsonl|ldjson)$", _handle_json_file),
        (r"\.doc$", _handle_legacy_doc_file),
    )
    for pattern, handler in handlers:
        if re.search(pattern, filename, re.IGNORECASE):
            return handler
    return None


def _collect_embed_results(ctx):
    if not ctx.is_root:
        return []
    if ctx.binary is None:
        raise RuntimeError("Embedding extraction from file path is not supported.")

    embed_res = []
    for embed_filename, embed_bytes in extract_embed_file(ctx.binary):
        try:
            sub_res = (
                chunk(
                    embed_filename,
                    binary=embed_bytes,
                    lang=ctx.lang,
                    callback=ctx.callback,
                    is_root=False,
                    **ctx.kwargs,
                )
                or []
            )
            embed_res.extend(sub_res)
        except Exception as exc:
            if ctx.callback:
                ctx.callback(0.05, f"Failed to chunk embed {embed_filename}: {exc}")
    return embed_res


def _collect_url_results(url_sources, ctx):
    if not url_sources or not ctx.parser_config.get("analyze_hyperlink", False) or not ctx.is_root:
        return []

    url_res = []
    for index, url in enumerate(url_sources):
        html_bytes, _metadata = extract_html(url)
        if not html_bytes:
            continue
        try:
            sub_url_res = chunk(
                url,
                html_bytes,
                callback=ctx.callback,
                lang=ctx.lang,
                is_root=False,
                **ctx.kwargs,
            )
        except Exception as exc:
            logging.info("Failed to chunk url in registered file type %s: %s", url, exc)
            sub_url_res = chunk(
                f"{index}.html",
                html_bytes,
                callback=ctx.callback,
                lang=ctx.lang,
                is_root=False,
                **ctx.kwargs,
            )
        url_res.extend(sub_url_res)
    return url_res


def _normalize_section_images(section_images):
    if section_images and all(image is None for image in section_images):
        return None
    return section_images


def _merge_markdown_sections(sections, section_images, parser_config):
    merged_chunks = []
    merged_images = []
    chunk_limit = max(0, int(parser_config.get("chunk_token_num", 128)))
    overlapped_percent = int(parser_config.get("overlapped_percent", 0))
    overlapped_percent = max(0, min(overlapped_percent, 90))
    current_text = ""
    current_tokens = 0
    current_image = None

    for idx, sec in enumerate(sections):
        text = sec[0] if isinstance(sec, tuple) else sec
        sec_tokens = num_tokens_from_string(text)
        sec_image = section_images[idx] if section_images and idx < len(section_images) else None
        if current_text and current_tokens + sec_tokens > chunk_limit:
            merged_chunks.append(current_text)
            merged_images.append(current_image)
            overlap_part = ""
            if overlapped_percent > 0:
                overlap_len = int(len(current_text) * overlapped_percent / 100)
                if overlap_len > 0:
                    overlap_part = current_text[-overlap_len:]
            current_text = overlap_part
            current_tokens = num_tokens_from_string(current_text)
            current_image = current_image if overlap_part else None

        current_text = f"{current_text}\n{text}" if current_text else text
        current_tokens += sec_tokens
        if sec_image:
            current_image = concat_img(current_image, sec_image) if current_image else sec_image

    if current_text:
        merged_chunks.append(current_text)
        merged_images.append(current_image)
    return merged_chunks, merged_images


def _extend_result_from_sections(body, ctx):
    if not body.sections:
        return list(body.res)

    res = list(body.res)
    if body.is_markdown:
        chunks, merged_images = _merge_markdown_sections(
            body.sections,
            body.section_images,
            ctx.parser_config,
        )
        has_images = merged_images and any(image is not None for image in merged_images)
        if has_images:
            res.extend(
                tokenize_chunks_with_images(
                    chunks,
                    ctx.doc,
                    ctx.is_english,
                    merged_images,
                    child_delimiters_pattern=ctx.child_delimiters,
                )
            )
        else:
            res.extend(
                tokenize_chunks(
                    chunks,
                    ctx.doc,
                    ctx.is_english,
                    body.pdf_parser,
                    child_delimiters_pattern=ctx.child_delimiters,
                )
            )
        return res

    section_images = _normalize_section_images(body.section_images)
    if section_images:
        chunks, images = naive_merge_with_images(
            body.sections,
            section_images,
            int(ctx.parser_config.get("chunk_token_num", 128)),
            ctx.parser_config.get("delimiter", "\n!?。；！？"),
        )
        res.extend(
            tokenize_chunks_with_images(
                chunks,
                ctx.doc,
                ctx.is_english,
                images,
                child_delimiters_pattern=ctx.child_delimiters,
            )
        )
        return res

    chunks = naive_merge(
        body.sections,
        int(ctx.parser_config.get("chunk_token_num", 128)),
        ctx.parser_config.get("delimiter", "\n!?。；！？"),
    )
    res.extend(
        tokenize_chunks(
            chunks,
            ctx.doc,
            ctx.is_english,
            body.pdf_parser,
            child_delimiters_pattern=ctx.child_delimiters,
        )
    )
    return res


def by_deepdoc(
    filename,
    binary=None,
    from_page=0,
    to_page=100000,
    lang="Chinese",
    callback=None,
    pdf_cls=None,
    **kwargs,
):
    pdf_parser = pdf_cls() if pdf_cls else Pdf()
    sections, tables = pdf_parser(
        _parser_source(filename, binary),
        from_page=from_page,
        to_page=to_page,
        callback=callback,
    )
    tables = vision_figure_parser_pdf_wrapper(tbls=tables, callback=callback, **kwargs)
    return sections, tables, pdf_parser


def by_mineru(
    filename,
    binary=None,
    from_page=0,
    to_page=100000,
    lang="Chinese",
    callback=None,
    pdf_cls=None,
    **kwargs,
):
    from app.deepdoc.parser.mineru_parser import MinerUParser

    mineru_executable = os.environ.get("MINERU_EXECUTABLE", "mineru")
    mineru_api = os.environ.get("MINERU_APISERVER", "http://host.docker.internal:9987")
    pdf_parser = MinerUParser(mineru_path=mineru_executable, mineru_api=mineru_api)
    parse_method = kwargs.get("parse_method", "raw")

    if not pdf_parser.check_installation():
        callback(-1, "MinerU not found.")
        return None, None, pdf_parser

    sections, tables = pdf_parser.parse_pdf(
        filepath=filename,
        binary=binary,
        callback=callback,
        output_dir=os.environ.get("MINERU_OUTPUT_DIR", ""),
        backend=os.environ.get("MINERU_BACKEND", "pipeline"),
        server_url=os.environ.get("MINERU_SERVER_URL", ""),
        delete_output=bool(int(os.environ.get("MINERU_DELETE_OUTPUT", 1))),
        parse_method=parse_method,
    )
    return sections, tables, pdf_parser


def by_docling(
    filename,
    binary=None,
    from_page=0,
    to_page=100000,
    lang="Chinese",
    callback=None,
    pdf_cls=None,
    **kwargs,
):
    from app.deepdoc.parser.docling_parser import DoclingParser

    pdf_parser = DoclingParser()
    parse_method = kwargs.get("parse_method", "raw")

    if not pdf_parser.check_installation():
        callback(-1, "Docling not found.")
        return None, None, pdf_parser

    sections, tables = pdf_parser.parse_pdf(
        filepath=filename,
        binary=binary,
        callback=callback,
        output_dir=os.environ.get("MINERU_OUTPUT_DIR", ""),
        delete_output=bool(int(os.environ.get("MINERU_DELETE_OUTPUT", 1))),
        parse_method=parse_method,
    )
    return sections, tables, pdf_parser


def by_tcadp(
    filename,
    binary=None,
    from_page=0,
    to_page=100000,
    lang="Chinese",
    callback=None,
    pdf_cls=None,
    **kwargs,
):
    from app.deepdoc.parser.tcadp_parser import TCADPParser

    tcadp_parser = TCADPParser()

    if not tcadp_parser.check_installation():
        callback(-1, "TCADP parser not available. Please check Tencent Cloud API configuration.")
        return None, None, tcadp_parser

    sections, tables = tcadp_parser.parse_pdf(
        filepath=filename,
        binary=binary,
        callback=callback,
        output_dir=os.environ.get("TCADP_OUTPUT_DIR", ""),
        file_type="PDF",
    )
    return sections, tables, tcadp_parser


def by_plaintext(filename, binary=None, from_page=0, to_page=100000, callback=None, **kwargs):
    # Vision parsing requires integrated-internal LLM services which are stubbed in this repo.
    # Fail soft to plaintext parsing so Integrated pipeline chunking remains usable out of the box.
    pdf_parser = _load_plaintext_parser(callback=callback, **kwargs)
    sections, tables = pdf_parser(
        _parser_source(filename, binary),
        from_page=from_page,
        to_page=to_page,
        callback=callback,
    )
    return sections, tables, pdf_parser


PARSERS = {
    "deepdoc": by_deepdoc,
    "mineru": by_mineru,
    "docling": by_docling,
    "tcadp": by_tcadp,
    "plaintext": by_plaintext,  # default
}


class Docx(DocxParser):
    def __init__(self):
        pass

    @staticmethod
    def _load_related_image_blob(document, embed):
        try:
            related_part = document.part.related_parts[embed]
            return related_part.image.blob
        except UnrecognizedImageError:
            logging.info("Unrecognized image format. Skipping image.")
        except UnexpectedEndOfFileError:
            logging.info("EOF was unexpectedly encountered while reading an image stream. Skipping image.")
        except (InvalidImageStreamError, UnicodeDecodeError):
            logging.info(CORRUPTED_IMAGE_LOG)
        except Exception:
            logging.info(CORRUPTED_IMAGE_LOG)
        return None

    @staticmethod
    def _image_from_blob(image_blob):
        try:
            return Image.open(BytesIO(image_blob)).convert("RGB")
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
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
        match = DOCX_HEADING_RE.search(style_name)
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
            heading = Docx._heading_from_paragraph(block)
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
        try:
            while cell_index < len(row.cells):
                span = 1
                cell = row.cells[cell_index]
                for sibling_index in range(cell_index + 1, len(row.cells)):
                    if cell.text != row.cells[sibling_index].text:
                        break
                    span += 1
                    cell_index = sibling_index
                cell_index += 1
                if span == 1:
                    html += f"<td>{cell.text}</td>"
                else:
                    html += f"<td colspan='{span}'>{cell.text}</td>"
        except Exception as exc:
            logging.warning("Error parsing table, ignore: %s", exc)
        return f"{html}</tr>"

    def _process_paragraph(self, lines, last_image, paragraph):
        if paragraph.text.strip():
            style_name = _paragraph_style_name(paragraph)
            if style_name == "Caption":
                former_image, last_image = self._consume_caption_image(lines, last_image)
                lines.append((self.__clean(paragraph.text), [former_image], style_name))
                return last_image

            current_image = self.get_picture(self.doc, paragraph)
            image_list = [current_image]
            if last_image:
                image_list.insert(0, last_image)
                last_image = None
            lines.append((self.__clean(paragraph.text), image_list, style_name))
            return last_image

        current_image = self.get_picture(self.doc, paragraph)
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
            res_img = image if res_img is None else concat_img(res_img, image)
        return res_img

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

    def __call__(self, filename, binary=None, from_page=0, to_page=100000):
        self.doc = Document(filename) if not binary else Document(BytesIO(binary))
        pn = 0
        lines = []
        last_image = None
        for paragraph in self.doc.paragraphs:
            if pn > to_page:
                break
            if from_page <= pn < to_page:
                last_image = self._process_paragraph(lines, last_image, paragraph)
            pn += self._page_break_count(paragraph)
        new_line = [(line[0], reduce(concat_img, line[1]) if line[1] else None) for line in lines]

        tbls = []
        for index, table in enumerate(self.doc.tables):
            title = self.__get_nearest_title(index, filename)
            html = "<table>"
            if title:
                html += f"<caption>Table Location: {title}</caption>"
            for row in table.rows:
                html += self._row_to_html(row)
            html += "</table>"
            tbls.append(((None, html), ""))
        return new_line, tbls

    def to_markdown(self, filename=None, binary=None, inline_images: bool = True):
        """
        This function uses mammoth, licensed under the BSD 2-Clause License.
        """

        import base64
        import uuid

        import mammoth
        from markdownify import markdownify

        docx_file = BytesIO(binary) if binary else open(filename, "rb")

        def _convert_image_to_base64(image):
            try:
                with image.open() as image_file:
                    image_bytes = image_file.read()
                encoded = base64.b64encode(image_bytes).decode("utf-8")
                base64_url = f"data:{image.content_type};base64,{encoded}"

                alt_name = "image"
                alt_name = f"img_{uuid.uuid4().hex[:8]}"

                return {"src": base64_url, "alt": alt_name}
            except Exception as e:
                logging.warning(f"Failed to convert image to base64: {e}")
                return {"src": "", "alt": "image"}

        try:
            if inline_images:
                result = mammoth.convert_to_html(
                    docx_file,
                    convert_image=mammoth.images.img_element(_convert_image_to_base64),
                )
            else:
                result = mammoth.convert_to_html(docx_file)

            html = result.value

            markdown_text = markdownify(html)
            return markdown_text

        finally:
            if not binary:
                docx_file.close()


class Pdf(PdfParser):
    def __init__(self):
        super().__init__()

    def __call__(
        self, filename, binary=None, from_page=0, to_page=100000, zoomin=3, callback=None, separate_tables_figures=False
    ):
        start = timer()
        first_start = start
        callback(msg="OCR started")
        self.__images__(filename if not binary else binary, zoomin, from_page, to_page, callback)
        callback(msg="OCR finished ({:.2f}s)".format(timer() - start))
        logging.info("OCR({}~{}): {:.2f}s".format(from_page, to_page, timer() - start))

        start = timer()
        self._layouts_rec(zoomin)
        callback(0.63, "Layout analysis ({:.2f}s)".format(timer() - start))

        start = timer()
        self._table_transformer_job(zoomin)
        callback(0.65, "Table analysis ({:.2f}s)".format(timer() - start))

        start = timer()
        self._text_merge(zoomin=zoomin)
        callback(0.67, "Text merged ({:.2f}s)".format(timer() - start))

        if separate_tables_figures:
            tbls, figures = self._extract_table_figure(True, zoomin, True, True, True)
            self._concat_downward()
            logging.info("layouts cost: {}s".format(timer() - first_start))
            return [(b["text"], self._line_tag(b, zoomin)) for b in self.boxes], tbls, figures
        else:
            tbls = self._extract_table_figure(True, zoomin, True, True)
            self._naive_vertical_merge()
            self._concat_downward()
            self._final_reading_order_merge()
            # self._filter_forpages()
            logging.info("layouts cost: {}s".format(timer() - first_start))
            return [(b["text"], self._line_tag(b, zoomin)) for b in self.boxes], tbls


class Markdown(MarkdownParser):
    @staticmethod
    def _append_unique_ref(urls, seen, url, line_no):
        key = (url, line_no)
        if key in seen:
            return
        urls.append({"url": url, "line": line_no})
        seen.add(key)

    @staticmethod
    def _line_number_from_offset(newline_offsets, position):
        for index, offset in enumerate(newline_offsets):
            if position <= offset:
                return index
        return 0

    @classmethod
    def _scan_inline_image_refs(cls, lines, urls, seen):
        for line_no, line in enumerate(lines):
            for url in MARKDOWN_IMAGE_RE.findall(line):
                cls._append_unique_ref(urls, seen, url, line_no)
            for url in HTML_IMAGE_RE.findall(line):
                cls._append_unique_ref(urls, seen, url, line_no)

    @classmethod
    def _scan_cross_line_image_refs(cls, text, urls, seen):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(text, "html.parser")
        newline_offsets = [match.start() for match in re.finditer(r"\n", text)] + [len(text)]
        for img_tag in soup.find_all("img"):
            src = img_tag.get("src")
            if not src:
                continue
            tag_str = str(img_tag)
            position = text.find(tag_str)
            if position == -1:
                position = max(text.find(src), 0)
            line_no = cls._line_number_from_offset(newline_offsets, position)
            cls._append_unique_ref(urls, seen, src, line_no)

    def md_to_html(self, sections):
        if not sections:
            return []
        if isinstance(sections, type("")):
            text = sections
        elif isinstance(sections[0], type("")):
            text = sections[0]
        else:
            return []

        from bs4 import BeautifulSoup

        html_content = markdown(text)
        soup = BeautifulSoup(html_content, "html.parser")
        return soup

    def get_hyperlink_urls(self, soup):
        if soup:
            return {a.get("href") for a in soup.find_all("a") if a.get("href")}
        return []

    def extract_image_urls_with_lines(self, text):
        urls = []
        seen = set()
        lines = text.splitlines()
        self._scan_inline_image_refs(lines, urls, seen)
        try:
            self._scan_cross_line_image_refs(text, urls, seen)
        except Exception as exc:
            logging.debug("Failed to extract image URLs from markdown text: %s", exc)
        return urls

    def load_images_from_urls(self, urls, cache=None):
        from pathlib import Path

        cache = cache or {}
        images = []
        http_client = httpx.Client(follow_redirects=True, timeout=30.0)
        for url in urls:
            if url in cache:
                if cache[url]:
                    images.append(cache[url])
                continue
            img_obj = None
            try:
                if url.startswith(("http://", "https://")):
                    response = http_client.get(url)
                    if response.status_code == 200 and response.headers.get("Content-Type", "").startswith("image/"):
                        img_obj = Image.open(BytesIO(response.content)).convert("RGB")
                else:
                    local_path = Path(url)
                    if local_path.exists():
                        img_obj = Image.open(url).convert("RGB")
                    else:
                        logging.warning(f"Local image file not found: {url}")
            except Exception as e:
                logging.error(f"Failed to download/open image from {url}: {e}")
            cache[url] = img_obj
            if img_obj:
                images.append(img_obj)
        http_client.close()
        return images, cache

    def __call__(self, filename, binary=None, separate_tables=True, delimiter=None, return_section_images=False):
        if binary:
            encoding = find_codec(binary)
            txt = binary.decode(encoding, errors="ignore")
        else:
            with open(filename, "r") as f:
                txt = f.read()

        _remainder, tables = self.extract_tables_and_remainder(f"{txt}\n", separate_tables=separate_tables)
        # To eliminate duplicate tables in chunking result, uncomment code below and
        # set separate_tables to True in this method's caller.
        # extractor = MarkdownElementExtractor(remainder)
        image_refs = self.extract_image_urls_with_lines(txt)
        MarkdownElementExtractor = getattr(deepdoc_parser, "MarkdownElementExtractor", None)

        if MarkdownElementExtractor is None:
            # Fallback: keep the whole markdown document as a single section.
            lines = txt.splitlines()
            element_sections = [{"content": txt, "start_line": 0, "end_line": max(0, len(lines) - 1)}]
        else:
            extractor = MarkdownElementExtractor(txt)
            element_sections = extractor.extract_elements(delimiter, include_meta=True)

        sections = []
        section_images = []
        image_cache = {}
        for element in element_sections:
            content = element["content"]
            start_line = element["start_line"]
            end_line = element["end_line"]
            urls_in_section = [ref["url"] for ref in image_refs if start_line <= ref["line"] <= end_line]
            imgs = []
            if urls_in_section:
                imgs, image_cache = self.load_images_from_urls(urls_in_section, image_cache)
            combined_image = None
            if imgs:
                combined_image = reduce(concat_img, imgs) if len(imgs) > 1 else imgs[0]
            sections.append((content, ""))
            section_images.append(combined_image)

        tbls = []
        for table in tables:
            tbls.append(((None, markdown(table, extensions=["markdown.extensions.tables"])), ""))
        if return_section_images:
            return sections, tbls, section_images
        return sections, tbls


def load_from_xml_v2(baseURI, rels_item_xml):
    """
    Return |_SerializedRelationships| instance loaded with the
    relationships contained in *rels_item_xml*. Returns an empty
    collection if *rels_item_xml* is |None|.
    """
    srels = _SerializedRelationships()
    if rels_item_xml is not None:
        rels_elm = parse_xml(rels_item_xml)
        for rel_elm in rels_elm.Relationship_lst:
            if rel_elm.target_ref in ("../NULL", "NULL"):
                continue
            srels._srels.append(_SerializedRelationship(baseURI, rel_elm))
    return srels


def _handle_docx_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    url_sources = []
    if ctx.parser_config.get("analyze_hyperlink", False) and ctx.is_root:
        url_sources = list(extract_links_from_docx(ctx.binary))

    _SerializedRelationships.load_from_xml = load_from_xml_v2
    sections, tables = Docx()(ctx.filename, ctx.binary)
    tables = vision_figure_parser_docx_wrapper(
        sections=sections,
        tbls=tables,
        callback=ctx.callback,
        **ctx.kwargs,
    )
    res = tokenize_table(tables, ctx.doc, ctx.is_english)
    ctx.callback(0.8, "Finish parsing.")
    started = timer()
    chunks, images = naive_merge_docx(
        sections,
        int(ctx.parser_config.get("chunk_token_num", 128)),
        ctx.parser_config.get("delimiter", "\n!?。；！？"),
    )
    res.extend(
        tokenize_chunks_with_images(
            chunks,
            ctx.doc,
            ctx.is_english,
            images,
            child_delimiters_pattern=ctx.child_delimiters,
        )
    )
    logging.info("naive_merge(%s): %s", ctx.filename, timer() - started)
    return ChunkBody(res=res, url_sources=url_sources)


def _handle_pdf_file(ctx):
    layout_recognizer = ctx.parser_config.get("layout_recognize", "DeepDOC")
    url_sources = []
    if ctx.parser_config.get("analyze_hyperlink", False) and ctx.is_root:
        url_sources = list(extract_links_from_pdf(ctx.binary))
    if isinstance(layout_recognizer, bool):
        layout_recognizer = "DeepDOC" if layout_recognizer else "Plain Text"

    parser_name = layout_recognizer.strip().lower()
    parser = PARSERS.get(parser_name, by_plaintext)
    ctx.callback(0.1, "Start to parse.")
    sections, tables, pdf_parser = parser(
        filename=ctx.filename,
        binary=ctx.binary,
        from_page=ctx.from_page,
        to_page=ctx.to_page,
        lang=ctx.lang,
        callback=ctx.callback,
        layout_recognizer=layout_recognizer,
        **ctx.kwargs,
    )
    if not sections and not tables:
        return ChunkBody(return_now=True)
    if parser_name in ["tcadp", "docling", "mineru"]:
        ctx.parser_config["chunk_token_num"] = 0
    res = tokenize_table(tables, ctx.doc, ctx.is_english)
    ctx.callback(0.8, "Finish parsing.")
    return ChunkBody(
        res=res,
        sections=sections,
        pdf_parser=pdf_parser,
        url_sources=url_sources,
    )


def _handle_spreadsheet_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    layout_recognizer = ctx.parser_config.get("layout_recognize", "DeepDOC")
    if layout_recognizer == "TCADP Parser":
        from app.deepdoc.parser.tcadp_parser import TCADPParser

        tcadp_parser = TCADPParser(
            table_result_type=ctx.parser_config.get("table_result_type", "1"),
            markdown_image_response_type=ctx.parser_config.get("markdown_image_response_type", "1"),
        )
        if not tcadp_parser.check_installation():
            ctx.callback(-1, "TCADP parser not available. Please check Tencent Cloud API configuration.")
            return ChunkBody(return_now=True)

        file_type = "XLSX" if re.search(r"\.xlsx?$", ctx.filename, re.IGNORECASE) else "CSV"
        sections, tables = tcadp_parser.parse_pdf(
            filepath=ctx.filename,
            binary=ctx.binary,
            callback=ctx.callback,
            output_dir=os.environ.get("TCADP_OUTPUT_DIR", ""),
            file_type=file_type,
        )
        ctx.parser_config["chunk_token_num"] = 0
        res = tokenize_table(tables, ctx.doc, ctx.is_english)
        ctx.callback(0.8, "Finish parsing.")
        return ChunkBody(res=res, sections=sections)

    excel_parser = ExcelParser()
    if ctx.parser_config.get("html4excel"):
        sections = [(_, "") for _ in excel_parser.html(ctx.binary, 12) if _]
        ctx.parser_config["chunk_token_num"] = 0
    else:
        sections = [(_, "") for _ in excel_parser(ctx.binary) if _]
    return ChunkBody(sections=sections)


def _handle_text_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    sections = TxtParser()(
        ctx.filename,
        ctx.binary,
        ctx.parser_config.get("chunk_token_num", 128),
        ctx.parser_config.get("delimiter", "\n!?;。；！？"),
    )
    ctx.callback(0.8, "Finish parsing.")
    return ChunkBody(sections=sections)


def _enhance_markdown_sections(sections, section_images, ctx):
    try:
        vision_model = LLMBundle(str(ctx.kwargs.get("tenant_id", "") or ""), LLMType.IMAGE2TEXT)
        ctx.callback(0.2, "Visual model detected. Attempting to enhance figure extraction...")
    except Exception:
        vision_model = None

    if vision_model is None:
        logging.warning("No visual model detected. Skipping figure parsing enhancement.")
        return sections, section_images

    for index, (section_text, section_meta) in enumerate(sections):
        combined_image = section_images[index] if section_images and len(section_images) > index else None
        if combined_image is None:
            continue
        if section_images is None:
            section_images = [None] * len(sections)
        section_images[index] = combined_image
        markdown_vision_parser = VisionFigureParser(
            vision_model=vision_model,
            figures_data=[((combined_image, ["markdown image"]), [(0, 0, 0, 0, 0)])],
            **ctx.kwargs,
        )
        boosted_figures = markdown_vision_parser(callback=ctx.callback)
        figure_text = "\n\n".join(fig[0][1] for fig in boosted_figures)
        sections[index] = (f"{section_text}\n\n{figure_text}", section_meta)
    return sections, section_images


def _collect_markdown_hyperlinks(sections, markdown_parser):
    urls = set()
    for section_text, _section_meta in sections:
        soup = markdown_parser.md_to_html(section_text)
        urls.update(markdown_parser.get_hyperlink_urls(soup))
    return list(urls)


def _handle_markdown_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    markdown_parser = Markdown(int(ctx.parser_config.get("chunk_token_num", 128)))
    sections, tables, section_images = markdown_parser(
        ctx.filename,
        ctx.binary,
        separate_tables=False,
        delimiter=ctx.parser_config.get("delimiter", "\n!?;。；！？"),
        return_section_images=True,
    )
    sections, section_images = _enhance_markdown_sections(sections, section_images, ctx)
    url_sources = []
    if ctx.parser_config.get("hyperlink_urls", False) and ctx.is_root:
        url_sources = _collect_markdown_hyperlinks(sections, markdown_parser)
    res = tokenize_table(tables, ctx.doc, ctx.is_english)
    ctx.callback(0.8, "Finish parsing.")
    return ChunkBody(
        res=res,
        sections=sections,
        section_images=section_images,
        url_sources=url_sources,
        is_markdown=True,
    )


def _handle_html_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    chunk_token_num = int(ctx.parser_config.get("chunk_token_num", 128))
    sections = HtmlParser()(ctx.filename, ctx.binary, chunk_token_num)
    sections = [(_, "") for _ in sections if _]
    ctx.callback(0.8, "Finish parsing.")
    return ChunkBody(sections=sections)


def _handle_json_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    chunk_token_num = int(ctx.parser_config.get("chunk_token_num", 128))
    sections = JsonParser(chunk_token_num)(ctx.binary)
    sections = [(_, "") for _ in sections if _]
    ctx.callback(0.8, "Finish parsing.")
    return ChunkBody(sections=sections)


def _handle_legacy_doc_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    tika_parser = optional_import(
        "tika.parser",
        feature="integrated_pipeline_naive_doc_parser",
        pip_name="tika",
    )
    if tika_parser is None:
        ctx.callback(0.8, "tika not available. Unsupported .doc parsing. (hint: pip install tika)")
        logging.warning(
            "tika not available. Unsupported .doc parsing for %s. (hint: pip install tika)",
            ctx.filename,
        )
        return ChunkBody(return_now=True)

    parsed_doc = tika_parser.from_buffer(BytesIO(ctx.binary))
    if parsed_doc.get("content", None) is None:
        ctx.callback(0.8, f"tika.parser got empty content from {ctx.filename}.")
        logging.warning("tika.parser got empty content from %s.", ctx.filename)
        return ChunkBody(return_now=True)

    sections = parsed_doc["content"].split("\n")
    sections = [(_, "") for _ in sections if _]
    ctx.callback(0.8, "Finish parsing.")
    return ChunkBody(sections=sections)


def chunk(filename, binary=None, from_page=0, to_page=100000, lang="Chinese", callback=None, **kwargs):
    """
    Supported file formats are docx, pdf, excel, txt.
    This method apply the naive ways to chunk files.
    Successive text will be sliced into pieces using 'delimiter'.
    Next, these successive pieces are merge into chunks whose token number is no more than 'Max token number'.
    """
    ctx = _build_chunk_context(filename, binary, from_page, to_page, lang, callback, kwargs)
    embed_res = _collect_embed_results(ctx)
    handler = _resolve_chunk_handler(filename)
    if handler is None:
        raise NotImplementedError("file type not supported yet(pdf, xlsx, doc, docx, txt supported)")

    body = handler(ctx)
    if body.return_now:
        return body.res

    started = timer()
    res = _extend_result_from_sections(body, ctx)
    url_res = _collect_url_results(body.url_sources, ctx)
    logging.info("naive_merge(%s): %s", filename, timer() - started)
    if embed_res:
        res.extend(embed_res)
    if url_res:
        res.extend(url_res)
    if ctx.table_context_size or ctx.image_context_size:
        attach_media_context(res, ctx.table_context_size, ctx.image_context_size)
    return res


if __name__ == "__main__":
    import sys

    def dummy(prog=None, msg=""):
        pass

    chunk(sys.argv[1], from_page=0, to_page=10, callback=dummy)
