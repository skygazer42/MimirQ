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

from app.core.optional_deps import optional_import
from app.deepdoc.parser import HtmlParser, PdfParser
from app.deepdoc.parser.figure_parser import vision_figure_parser_docx_wrapper
from app.deepdoc.parser.utils import get_text
from app.third_party.integrated_pipeline.chunkers import naive_chunk as naive
from app.third_party.integrated_pipeline.chunkers.naive import PARSERS, by_plaintext
from app.third_party.integrated_pipeline.nlp import (
    attach_media_context,
    bullets_category,
    hierarchical_merge,
    is_english,
    make_colon_as_title,
    naive_merge,
    rag_tokenizer,
    random_choices,
    remove_contents_table,
    tokenize_chunks,
    tokenize_table,
)


class Pdf(PdfParser):
    def __call__(self, filename, binary=None, from_page=0, to_page=100000, zoomin=3, callback=None):
        from timeit import default_timer as timer

        start = timer()
        callback(msg="OCR started")
        self.__images__(filename if not binary else binary, zoomin, from_page, to_page, callback)
        callback(msg="OCR finished ({:.2f}s)".format(timer() - start))

        start = timer()
        self._layouts_rec(zoomin)
        callback(0.67, "Layout analysis ({:.2f}s)".format(timer() - start))
        logging.debug("layouts: {}".format(timer() - start))

        start = timer()
        self._table_transformer_job(zoomin)
        callback(0.68, "Table analysis ({:.2f}s)".format(timer() - start))

        start = timer()
        self._text_merge()
        tbls = self._extract_table_figure(True, zoomin, True, True)
        self._naive_vertical_merge()
        self._filter_forpages()
        self._merge_with_same_bullet()
        callback(0.8, "Text extraction ({:.2f}s)".format(timer() - start))

        return [(b["text"] + self._line_tag(b, zoomin), b.get("layoutno", "")) for b in self.boxes], tbls


def _default_parser_config(kwargs):
    return kwargs.get(
        "parser_config",
        {"chunk_token_num": 512, "delimiter": "\n!?。；！？", "layout_recognize": "DeepDOC"},
    )


def _build_doc(filename):
    doc = {"docnm_kwd": filename, "title_tks": rag_tokenizer.tokenize(re.sub(r"\.[a-zA-Z]+$", "", filename))}
    doc["title_sm_tks"] = rag_tokenizer.fine_grained_tokenize(doc["title_tks"])
    return doc


def _filter_docx_sections(sections):
    return [
        (item[0], item[1] if item[1] is not None else "") for item in sections if not isinstance(item[1], Image.Image)
    ]


def _parse_docx(filename, binary, from_page, to_page, callback, kwargs):
    callback(0.1, "Start to parse.")
    doc_parser = naive.Docx()
    sections, tbls = doc_parser(filename, binary=binary, from_page=from_page, to_page=to_page)
    remove_contents_table(sections, eng=is_english(random_choices([t for t, _ in sections], k=200)))
    tbls = vision_figure_parser_docx_wrapper(sections=sections, tbls=tbls, callback=callback, **kwargs)
    callback(0.8, "Finish parsing.")
    return _filter_docx_sections(sections), tbls, None


def _parse_pdf(filename, binary, from_page, to_page, lang, callback, parser_config, kwargs):
    layout_recognizer = parser_config.get("layout_recognize", "DeepDOC")
    if isinstance(layout_recognizer, bool):
        layout_recognizer = "DeepDOC" if layout_recognizer else "Plain Text"

    name = layout_recognizer.strip().lower()
    parser = PARSERS.get(name, by_plaintext)
    callback(0.1, "Start to parse.")
    sections, tbls, pdf_parser = parser(
        filename=filename,
        binary=binary,
        from_page=from_page,
        to_page=to_page,
        lang=lang,
        callback=callback,
        pdf_cls=Pdf,
        layout_recognizer=layout_recognizer,
        **kwargs,
    )
    if not sections and not tbls:
        return [], [], None
    if name in ["tcadp", "docling", "mineru"]:
        parser_config["chunk_token_num"] = 0

    sample_texts = [s if isinstance(s, str) else s[0] for s in sections]
    remove_contents_table(sections, eng=is_english(random_choices(sample_texts, k=200)))
    callback(0.8, "Finish parsing.")
    return sections, tbls, pdf_parser


def _parse_text_sections(filename, binary, callback):
    callback(0.1, "Start to parse.")
    txt = get_text(filename, binary)
    sections = [(line, "") for line in txt.split("\n") if line]
    remove_contents_table(sections, eng=is_english(random_choices([t for t, _ in sections], k=200)))
    callback(0.8, "Finish parsing.")
    return sections, [], None


def _parse_html_sections(filename, binary, callback):
    callback(0.1, "Start to parse.")
    sections = [(line, "") for line in HtmlParser()(filename, binary) if line]
    remove_contents_table(sections, eng=is_english(random_choices([t for t, _ in sections], k=200)))
    callback(0.8, "Finish parsing.")
    return sections, [], None


def _parse_doc_sections(filename, binary, callback):
    callback(0.1, "Start to parse.")
    tika_parser = optional_import("tika.parser", feature="integrated_pipeline_book_doc_parser", pip_name="tika")
    if tika_parser is None:
        callback(0.8, "tika not available. Unsupported .doc parsing. (hint: pip install tika)")
        logging.warning("tika not available. Unsupported .doc parsing for %s. (hint: pip install tika)", filename)
        return None

    doc_parsed = tika_parser.from_buffer(BytesIO(binary))
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
    parser_config = _default_parser_config(kwargs)
    doc = _build_doc(filename)
    parsed = _parse_sections(filename, binary, from_page, to_page, lang, callback, parser_config, kwargs)
    if parsed is None:
        return []

    sections, tbls, pdf_parser = parsed
    if not sections and not tbls:
        return []

    chunks = _merge_chunks(sections, kwargs)

    # is it English
    # is_english(random_choices([t for t, _ in sections], k=218))
    eng = lang.lower() == "english"

    res = tokenize_table(tbls, doc, eng)
    res.extend(tokenize_chunks(chunks, doc, eng, pdf_parser))
    table_ctx = max(0, int(parser_config.get("table_context_size", 0) or 0))
    image_ctx = max(0, int(parser_config.get("image_context_size", 0) or 0))
    if table_ctx or image_ctx:
        attach_media_context(res, table_ctx, image_ctx)

    return res


if __name__ == "__main__":
    import sys

    def dummy(prog=None, msg=""):
        pass

    chunk(sys.argv[1], from_page=1, to_page=10, callback=dummy)
