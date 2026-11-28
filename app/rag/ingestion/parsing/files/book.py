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

from PIL import Image

from app.infrastructure.runtime.dependencies import optional_import
from app.rag.ingestion.chunking.utils.chunk_records import (
    attach_media_context,
    build_chunk_document,
    tokenize_chunks,
    tokenize_table,
)
from app.rag.ingestion.chunking.utils.section_merging import naive_merge
from app.rag.ingestion.chunking.utils.section_structure import (
    bullets_category,
    hierarchical_merge,
    is_english,
    make_colon_as_title,
    random_choices,
    remove_contents_table,
)
from app.rag.ingestion.parsing.enrich.vlm_image_caption import enrich_figures
from app.rag.ingestion.parsing.files.general import (
    DEFAULT_PARSER_CONFIG,
    PARSERS,
    _close_owned_images,
    by_plaintext,
    close_pdf_parser_images,
)
from app.rag.ingestion.parsing.parsers.docx_parser import DocxParser
from app.rag.ingestion.parsing.parsers.html_parser import parse_html_sections
from app.rag.ingestion.parsing.parsers.pdf_layout import BookLayoutPdfParser
from app.rag.ingestion.parsing.utils.text import read_text_source


def _filter_docx_sections(sections):
    return [
        (item[0], item[1] if item[1] is not None else "") for item in sections if not isinstance(item[1], Image.Image)
    ]


def _parse_docx(filename, binary, from_page, to_page, callback, kwargs):
    callback(0.1, "Start to parse.")
    doc_parser = DocxParser()
    sections, tbls = doc_parser.parse_media(filename, binary=binary, from_page=from_page, to_page=to_page)
    images = {id(image): image for _text, image in sections if isinstance(image, Image.Image)}
    pending_error: BaseException | None = None
    try:
        remove_contents_table(sections, eng=is_english(random_choices([t for t, _ in sections], k=200)))
        tbls = enrich_figures(tbls=tbls, callback=callback)
        callback(0.8, "Finish parsing.")
        return _filter_docx_sections(sections), tbls, None
    except BaseException as exc:
        pending_error = exc
        raise
    finally:
        # This book strategy deliberately omits image-bearing sections.
        _close_owned_images(images.values(), pending_error=pending_error)


def _parse_pdf(filename, binary, from_page, to_page, lang, callback, parser_config, kwargs):
    layout_recognizer = parser_config.get("layout_recognize", "DeepDOC")
    if isinstance(layout_recognizer, bool):
        layout_recognizer = "DeepDOC" if layout_recognizer else "Plain Text"

    from app.infrastructure.model_policy import reject_retired_provider

    name = layout_recognizer.strip().lower()
    reject_retired_provider(name.replace(" ", "_"), capability="parser")
    parser = PARSERS.get(name, by_plaintext)
    callback(0.1, "Start to parse.")
    sections, tbls, pdf_parser = parser(
        filename=filename,
        binary=binary,
        from_page=from_page,
        to_page=to_page,
        lang=lang,
        callback=callback,
        pdf_cls=BookLayoutPdfParser,
        layout_recognizer=layout_recognizer,
        **kwargs,
    )
    if not sections and not tbls:
        close_pdf_parser_images(pdf_parser)
        return [], [], None
    try:
        if name in ["docling", "mineru"]:
            parser_config["chunk_token_num"] = 0
        sample_texts = [s if isinstance(s, str) else s[0] for s in sections]
        remove_contents_table(sections, eng=is_english(random_choices(sample_texts, k=200)))
        callback(0.8, "Finish parsing.")
        return sections, tbls, pdf_parser
    except BaseException as exc:
        close_pdf_parser_images(pdf_parser, pending_error=exc)
        raise


def _parse_text_sections(filename, binary, callback):
    callback(0.1, "Start to parse.")
    txt = read_text_source(filename, binary)
    sections = [(line, "") for line in txt.split("\n") if line]
    remove_contents_table(sections, eng=is_english(random_choices([t for t, _ in sections], k=200)))
    callback(0.8, "Finish parsing.")
    return sections, [], None


def _parse_html_sections(filename, binary, callback):
    callback(0.1, "Start to parse.")
    sections = [(line, "") for line in parse_html_sections(filename, binary) if line]
    remove_contents_table(sections, eng=is_english(random_choices([t for t, _ in sections], k=200)))
    callback(0.8, "Finish parsing.")
    return sections, [], None


def _parse_doc_sections(filename, binary, callback):
    callback(0.1, "Start to parse.")
    tika_parser = optional_import("tika.parser", feature="integrated_pipeline_book_doc_parser", pip_name="tika")
    if tika_parser is None:
        raise RuntimeError("Book .doc parsing requires tika")

    with BytesIO(binary) if binary is not None else open(filename, "rb") as source:
        doc_parsed = tika_parser.from_buffer(source)
    if doc_parsed.get("content", None) is None:
        callback(0.8, f"tika.parser got empty content from {filename}.")
        logging.warning(f"tika.parser got empty content from {filename}.")
        return None

    sections = [(line, "") for line in doc_parsed["content"].split("\n") if line]
    remove_contents_table(sections, eng=is_english(random_choices([t for t, _ in sections], k=200)))
    callback(0.8, "Finish parsing.")
    return sections, [], None


def _parse_sections(filename, binary, from_page, to_page, lang, callback, parser_config, kwargs):
    if re.search(r"\.docx$", filename, re.IGNORECASE):
        return _parse_docx(filename, binary, from_page, to_page, callback, kwargs)
    if re.search(r"\.pdf$", filename, re.IGNORECASE):
        return _parse_pdf(filename, binary, from_page, to_page, lang, callback, parser_config, kwargs)
    if re.search(r"\.txt$", filename, re.IGNORECASE):
        return _parse_text_sections(filename, binary, callback)
    if re.search(r"\.(htm|html)$", filename, re.IGNORECASE):
        return _parse_html_sections(filename, binary, callback)
    if re.search(r"\.doc$", filename, re.IGNORECASE):
        return _parse_doc_sections(filename, binary, callback)
    raise NotImplementedError("file type not supported yet(doc, docx, pdf, txt supported)")


def _merge_chunks(sections, kwargs):
    make_colon_as_title(sections)
    bull = bullets_category(list(random_choices([t for t, _ in sections], k=100)))
    if bull >= 0:
        return ["\n".join(ck) for ck in hierarchical_merge(bull, sections, 5)]

    split_sections = [s.split("@") for s, _ in sections]
    split_sections = [(pr[0], "@" + pr[1]) if len(pr) == 2 else (pr[0], "") for pr in split_sections]
    return naive_merge(split_sections, kwargs.get("chunk_token_num", 256), kwargs.get("delimer", "\n。；！？"))


def chunk(filename, binary=None, from_page=0, to_page=100000, lang="Chinese", callback=None, **kwargs):
    """
    Supported file formats are docx, pdf, txt.
    Since a book is long and not all the parts are useful, if it's a PDF,
    please setup the page ranges for every book in order eliminate negative effects and save elapsed computing time.
    """
    parser_config = dict(kwargs.get("parser_config", DEFAULT_PARSER_CONFIG))
    callback = callback if callback is not None else lambda _progress, _message: None
    doc = build_chunk_document(filename)
    parsed = _parse_sections(filename, binary, from_page, to_page, lang, callback, parser_config, kwargs)
    if parsed is None:
        return []

    sections, tbls, pdf_parser = parsed
    pending_error: BaseException | None = None
    try:
        if not sections and not tbls:
            return []
        chunks = _merge_chunks(sections, kwargs)
        eng = lang.lower() == "english"
        res = tokenize_table(tbls, doc, eng)
        res.extend(tokenize_chunks(chunks, doc, eng, pdf_parser))
        table_ctx = max(0, int(parser_config.get("table_context_size", 0) or 0))
        image_ctx = max(0, int(parser_config.get("image_context_size", 0) or 0))
        if table_ctx or image_ctx:
            attach_media_context(res, table_ctx, image_ctx)
        return res
    except BaseException as exc:
        pending_error = exc
        raise
    finally:
        close_pdf_parser_images(pdf_parser, pending_error=pending_error)
