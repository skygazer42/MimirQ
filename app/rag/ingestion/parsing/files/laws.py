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
import re
from io import BytesIO

from docx import Document

from app.infrastructure.runtime.dependencies import optional_import
from app.rag.ingestion.chunking.utils.chunk_records import build_chunk_document, tokenize_chunks
from app.rag.ingestion.chunking.utils.section_structure import (
    SectionNode,
    bullets_category,
    docx_question_level,
    make_colon_as_title,
    remove_contents_table,
    tree_merge,
)
from app.rag.ingestion.parsing.files.general import (
    DEFAULT_PARSER_CONFIG,
    PARSERS,
    by_plaintext,
    close_pdf_parser_images,
)
from app.rag.ingestion.parsing.parsers.docx_parser import DocxParser
from app.rag.ingestion.parsing.parsers.html_parser import parse_html_sections
from app.rag.ingestion.parsing.parsers.pdf_layout import LegalLayoutPdfParser
from app.rag.ingestion.parsing.utils.text import read_text_source


def parse_legal_docx_sections(filename, binary=None, from_page=0, to_page=100000):
    if binary is None:
        doc = Document(filename)
    else:
        with BytesIO(binary) as source:
            doc = Document(source)
    pn = 0
    lines = []
    level_set = set()
    bull = bullets_category([p.text for p in doc.paragraphs])
    for p in doc.paragraphs:
        if pn >= to_page:
            break
        if pn >= from_page:
            question_level, p_text = docx_question_level(p, bull)
            if p_text.strip("\n"):
                lines.append((question_level, p_text))
                level_set.add(question_level)
        pn += DocxParser._page_break_count(p)

    sorted_levels = sorted(level_set)
    if not sorted_levels:
        return []

    h2_level = sorted_levels[1] if len(sorted_levels) > 1 else 1
    h2_level = sorted_levels[-2] if h2_level == sorted_levels[-1] and len(sorted_levels) > 2 else h2_level

    root = SectionNode(level=0, depth=h2_level, texts=[])
    root.build_tree(lines)

    return [element for element in root.get_tree() if element]


def _parse_docx(filename, binary, from_page, to_page, callback):
    callback(0.1, "Start to parse.")
    chunks = parse_legal_docx_sections(filename, binary, from_page=from_page, to_page=to_page)
    callback(0.7, "Finish parsing.")
    return [], None, chunks


def _parse_pdf(filename, binary, from_page, to_page, lang, callback, parser_config, kwargs):
    layout_recognizer = parser_config.get("layout_recognize", "DeepDOC")
    if isinstance(layout_recognizer, bool):
        layout_recognizer = "DeepDOC" if layout_recognizer else "Plain Text"

    from app.infrastructure.model_policy import reject_retired_provider

    name = layout_recognizer.strip().lower()
    reject_retired_provider(name.replace(" ", "_"), capability="parser")
    parser = PARSERS.get(name, by_plaintext)
    callback(0.1, "Start to parse.")
    raw_sections, tables, pdf_parser = parser(
        filename=filename,
        binary=binary,
        from_page=from_page,
        to_page=to_page,
        lang=lang,
        callback=callback,
        pdf_cls=LegalLayoutPdfParser,
        layout_recognizer=layout_recognizer,
        **kwargs,
    )
    if not raw_sections and not tables:
        close_pdf_parser_images(pdf_parser)
        return [], None, []
    try:
        if name in ["docling", "mineru"]:
            parser_config["chunk_token_num"] = 0
        sections = [txt + poss for txt, poss in raw_sections]
        callback(0.8, "Finish parsing.")
        return sections, pdf_parser, None
    except BaseException as exc:
        close_pdf_parser_images(pdf_parser, pending_error=exc)
        raise


def _parse_text_sections(filename, binary, callback):
    callback(0.1, "Start to parse.")
    sections = [s for s in read_text_source(filename, binary).split("\n") if s]
    callback(0.8, "Finish parsing.")
    return sections, None, None


def _parse_html_sections(filename, binary, callback):
    callback(0.1, "Start to parse.")
    sections = [s for s in parse_html_sections(filename, binary) if s]
    callback(0.8, "Finish parsing.")
    return sections, None, None


def _parse_doc_sections(filename, binary, callback):
    callback(0.1, "Start to parse.")
    tika_parser = optional_import("tika.parser", feature="integrated_pipeline_laws_doc_parser", pip_name="tika")
    if tika_parser is None:
        raise RuntimeError("Legal .doc parsing requires tika")

    with BytesIO(binary) if binary is not None else open(filename, "rb") as source:
        doc_parsed = tika_parser.from_buffer(source)
    if doc_parsed.get("content", None) is None:
        callback(0.8, f"tika.parser got empty content from {filename}.")
        logging.warning(f"tika.parser got empty content from {filename}.")
        return None

    sections = [s for s in doc_parsed["content"].split("\n") if s]
    callback(0.8, "Finish parsing.")
    return sections, None, None


def _parse_sections(filename, binary, from_page, to_page, lang, callback, parser_config, kwargs):
    if re.search(r"\.docx$", filename, re.IGNORECASE):
        return _parse_docx(filename, binary, from_page, to_page, callback)
    if re.search(r"\.pdf$", filename, re.IGNORECASE):
        return _parse_pdf(filename, binary, from_page, to_page, lang, callback, parser_config, kwargs)
    if re.search(r"\.(txt|md|markdown|mdx)$", filename, re.IGNORECASE):
        return _parse_text_sections(filename, binary, callback)
    if re.search(r"\.(htm|html)$", filename, re.IGNORECASE):
        return _parse_html_sections(filename, binary, callback)
    if re.search(r"\.doc$", filename, re.IGNORECASE):
        return _parse_doc_sections(filename, binary, callback)
    raise NotImplementedError("file type not supported yet(doc, docx, pdf, txt supported)")


def chunk(filename, binary=None, from_page=0, to_page=100000, lang="Chinese", callback=None, **kwargs):
    """
    Supported file formats are docx, pdf, txt.
    """
    parser_config = dict(kwargs.get("parser_config", DEFAULT_PARSER_CONFIG))
    callback = callback if callback is not None else lambda _progress, _message: None
    doc = build_chunk_document(filename)
    # is it English
    eng = lang.lower() == "english"  # is_english(sections)
    parsed = _parse_sections(filename, binary, from_page, to_page, lang, callback, parser_config, kwargs)
    if parsed is None:
        return []

    sections, pdf_parser, chunks = parsed
    pending_error: BaseException | None = None
    try:
        if chunks is not None:
            return tokenize_chunks(chunks, doc, eng, None)
        if not sections:
            return []
        remove_contents_table(sections, eng)
        make_colon_as_title(sections)
        bull = bullets_category(sections)
        res = tree_merge(bull, sections, 2)
        if not res:
            callback(0.99, "No chunk parsed out.")
        return tokenize_chunks(res, doc, eng, pdf_parser)
    except BaseException as exc:
        pending_error = exc
        raise
    finally:
        close_pdf_parser_images(pdf_parser, pending_error=pending_error)
