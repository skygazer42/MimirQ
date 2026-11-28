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
from contextlib import ExitStack, closing
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from timeit import default_timer as timer
from typing import Any

import httpx
from markdown import markdown
from PIL import Image

from app.infrastructure.runtime.dependencies import optional_import
from app.infrastructure.tokens import num_tokens_from_string
from app.rag.ingestion.chunking.utils.chunk_records import (
    attach_media_context,
    build_chunk_document,
    tokenize_chunks,
    tokenize_chunks_with_images,
    tokenize_table,
)
from app.rag.ingestion.chunking.utils.section_merging import naive_merge, naive_merge_docx, naive_merge_with_images
from app.rag.ingestion.parsing.enrich.image_references import normalize_local_image_ref
from app.rag.ingestion.parsing.enrich.image_understanding import concat_images
from app.rag.ingestion.parsing.enrich.vlm_image_caption import VisionFigureParser, enrich_figures
from app.rag.ingestion.parsing.parsers.docx_parser import DocxParser
from app.rag.ingestion.parsing.parsers.excel_parser import ExcelParser
from app.rag.ingestion.parsing.parsers.html_parser import parse_html_sections
from app.rag.ingestion.parsing.parsers.json_parser import JsonParser
from app.rag.ingestion.parsing.parsers.pdf_layout import GeneralLayoutPdfParser, VisionPdfParser
from app.rag.ingestion.parsing.parsers.pdf_parser import PlainPdfParser
from app.rag.ingestion.parsing.parsers.text_parser import extract_markdown_tables_and_remainder, parse_text_sections
from app.rag.ingestion.parsing.utils.text import read_text_source
from app.rag.llm.vision_client import VisionCaptionClient

DEFAULT_PARSER_CONFIG = {
    "chunk_token_num": 512,
    "delimiter": "\n!?。；！？",
    "layout_recognize": "DeepDOC",
}
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
HTML_IMAGE_RE = re.compile(r"""src=["']([^"'>\s]+)""", re.IGNORECASE)


def _close_owned_images(images, *, pending_error: BaseException | None) -> None:
    resources = ExitStack()
    for image in images:
        resources.callback(image.close)
    try:
        resources.close()
    except BaseException as exc:
        if pending_error is None:
            raise
        pending_error.add_note(f"Integrated image cleanup failed: {type(exc).__name__}")
        logging.warning("Integrated image cleanup failed while propagating an error", exc_info=True)


def close_pdf_parser_images(parser, *, pending_error: BaseException | None = None) -> None:
    """Close backing page caches on the app's layout/MinerU parser implementations."""
    close_images = getattr(parser, "close_images", None)
    if close_images is None:
        # PlainPdfParser/DoclingServiceParser have no backing page image cache.
        return
    try:
        close_images()
    except BaseException as exc:
        if pending_error is None:
            raise
        pending_error.add_note(f"PDF parser image cleanup failed: {type(exc).__name__}")
        logging.warning("PDF parser image cleanup failed while propagating an error", exc_info=True)


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
    owned_images: dict[int, Any] = field(default_factory=dict)
    layout_parser: Any = None


@dataclass
class ChunkBody:
    res: list[Any] = field(default_factory=list)
    sections: list[Any] = field(default_factory=list)
    pdf_parser: Any = None
    section_images: list[Any] | None = None
    is_markdown: bool = False
    return_now: bool = False


def _own_chunk_images(ctx: ChunkContext, images) -> None:
    for image in images:
        if isinstance(image, Image.Image):
            ctx.owned_images[id(image)] = image


def _parser_source(filename, binary):
    return filename if binary is None else binary


def _load_plaintext_parser(callback=None, **kwargs):
    if kwargs.get("layout_recognizer", "") == "Plain Text":
        return PlainPdfParser()

    layout_name = kwargs.get("layout_recognizer", "").strip()
    try:
        vision_model = VisionCaptionClient(model_name=layout_name)
        return VisionPdfParser(vision_model=vision_model)
    except Exception as exc:
        if callback is not None:
            callback(
                -1,
                (f"Vision layout_recognizer '{layout_name}' unavailable; falling back to Plain Text. ({exc})"),
            )
        return PlainPdfParser()


def _build_chunk_context(filename, binary, from_page, to_page, lang, callback, kwargs):
    parser_config = kwargs.get("parser_config")
    parser_config = dict(DEFAULT_PARSER_CONFIG if parser_config is None else parser_config)
    parser_kwargs = dict(kwargs)
    parser_kwargs["parser_config"] = parser_config

    child_delimiters = re.findall(r"`([^`]+)`", parser_config.get("children_delimiter", ""))
    child_delimiters = sorted(set(child_delimiters), key=lambda item: -len(item))
    child_delimiters = "|".join(re.escape(item) for item in child_delimiters if item)
    doc = build_chunk_document(filename)
    return ChunkContext(
        filename=filename,
        binary=binary,
        from_page=from_page,
        to_page=to_page,
        lang=lang,
        callback=callback if callback is not None else lambda _progress, _message: None,
        kwargs=parser_kwargs,
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


def _normalize_section_images(section_images):
    if section_images and all(image is None for image in section_images):
        return None
    return section_images


def _merge_markdown_sections(sections, section_images, parser_config, *, owned_images):
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
        if sec_image is not None:
            current_image = concat_images(current_image, sec_image) if current_image is not None else sec_image
            owned_images[id(current_image)] = current_image

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
            owned_images=ctx.owned_images,
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
        _own_chunk_images(ctx, images)
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
    pdf_parser = pdf_cls() if pdf_cls else GeneralLayoutPdfParser()
    images = []
    try:
        sections, tables = pdf_parser(
            _parser_source(filename, binary), from_page=from_page, to_page=to_page, callback=callback
        )
        images = [table[0][0] for table in tables if isinstance(table[0][0], Image.Image)]
        tables = enrich_figures(tbls=tables, callback=callback)
        return sections, tables, pdf_parser
    except BaseException as exc:
        _close_owned_images(images, pending_error=exc)
        close_pdf_parser_images(pdf_parser, pending_error=exc)
        raise


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
    from app.rag.ingestion.parsing.parsers.mineru_parser import MinerUResultParser

    mineru_api = os.environ.get("MINERU_APISERVER", "http://host.docker.internal:9987")
    pdf_parser = MinerUResultParser(mineru_api=mineru_api)
    parse_method = kwargs.get("parse_method", "raw")

    try:
        available, reason = pdf_parser.check_installation()
        if not available:
            if callback is not None:
                callback(-1, "MinerU not found.")
            raise RuntimeError(f"MinerU unavailable: {reason}")

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
    except BaseException as exc:
        close_pdf_parser_images(pdf_parser, pending_error=exc)
        raise


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
    from app.services.parsing.docling import DoclingServiceParser, validate_docling_max_pages

    if from_page != 0:
        raise ValueError("Integrated Docling parsing supports page ranges starting at zero only")
    validate_docling_max_pages(to_page)
    pdf_parser = DoclingServiceParser()

    if not pdf_parser.check_installation():
        if callback:
            callback(-1, f"Docling service unavailable: {pdf_parser.unavailable_reason}")
        raise RuntimeError(f"Docling service unavailable: {pdf_parser.unavailable_reason}")

    sections, tables = pdf_parser.parse_pdf(
        filepath=filename,
        binary=binary,
        callback=callback,
        max_pages=to_page,
    )
    return sections, tables, pdf_parser


def by_plaintext(filename, binary=None, from_page=0, to_page=100000, callback=None, **kwargs):
    # An unavailable configured vision model retains the plain-text parser fallback.
    pdf_parser = _load_plaintext_parser(callback=callback, **kwargs)
    try:
        sections, tables = pdf_parser(
            _parser_source(filename, binary), from_page=from_page, to_page=to_page, callback=callback
        )
        return sections, tables, pdf_parser
    except BaseException as exc:
        close_pdf_parser_images(pdf_parser, pending_error=exc)
        raise


PARSERS = {
    "deepdoc": by_deepdoc,
    "mineru": by_mineru,
    "docling": by_docling,
    "plaintext": by_plaintext,  # default
}


class Markdown:
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

    def load_images_from_urls(self, urls, cache=None, *, base_dir: Path):
        cache = {} if cache is None else cache
        images = []
        created = {}
        if not urls:
            return images, cache
        try:
            with httpx.Client(follow_redirects=True, timeout=30.0) as http_client:
                for url in urls:
                    if url in cache:
                        if cache[url] is not None:
                            images.append(cache[url])
                        continue
                    img_obj = None
                    try:
                        if url.lower().startswith(("http://", "https://")):
                            with http_client.stream("GET", url) as response:
                                if response.status_code == 200 and response.headers.get("Content-Type", "").startswith(
                                    "image/"
                                ):
                                    with BytesIO(response.read()) as source, closing(Image.open(source)) as decoded:
                                        img_obj = decoded.convert("RGB")
                                else:
                                    logging.debug("Markdown image HTTP status=%s", response.status_code)
                        else:
                            local_ref, error = normalize_local_image_ref(url)
                            if error is not None:
                                raise ValueError(error)
                            local_path = Path(local_ref)
                            if not local_path.is_absolute():
                                local_path = base_dir / local_path
                            if local_path.is_file():
                                with closing(Image.open(local_path)) as decoded:
                                    img_obj = decoded.convert("RGB")
                            else:
                                logging.debug("Markdown local image unavailable")
                    except Exception as exc:
                        if img_obj is not None:
                            _close_owned_images([img_obj], pending_error=exc)
                            img_obj = None
                        logging.warning("Markdown image loading failed (%s)", type(exc).__name__)
                    created[url] = img_obj
                    cache[url] = img_obj
                    if img_obj is not None:
                        images.append(img_obj)
            return images, cache
        except BaseException as exc:
            for url in created:
                cache.pop(url, None)
            _close_owned_images((image for image in created.values() if image is not None), pending_error=exc)
            raise

    def __call__(self, filename, binary=None, separate_tables=True, delimiter=None, return_section_images=False):
        txt = read_text_source(filename, binary)
        _remainder, tables = extract_markdown_tables_and_remainder(f"{txt}\n", separate_tables=separate_tables)
        sections = [(txt, "")]
        section_images = [None]
        owned_images = {}
        retained = set()
        pending_error: BaseException | None = None
        try:
            if return_section_images:
                image_refs = self.extract_image_urls_with_lines(txt)
                images, image_cache = self.load_images_from_urls(
                    [ref["url"] for ref in image_refs], base_dir=Path(filename).parent
                )
                owned_images.update((id(image), image) for image in image_cache.values() if image is not None)
                combined_image = None
                for image in images:
                    combined_image = concat_images(combined_image, image)
                    if combined_image is not None:
                        owned_images[id(combined_image)] = combined_image
                section_images[0] = combined_image

            tbls = [((None, markdown(table, extensions=["markdown.extensions.tables"])), "") for table in tables]
            if return_section_images:
                retained = {id(image) for image in section_images if image is not None}
                return sections, tbls, section_images
            return sections, tbls
        except BaseException as exc:
            pending_error = exc
            raise
        finally:
            _close_owned_images(
                (image for image_id, image in owned_images.items() if image_id not in retained),
                pending_error=pending_error,
            )


def _handle_docx_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    sections, tables = DocxParser().parse_media(ctx.filename, ctx.binary, from_page=ctx.from_page, to_page=ctx.to_page)
    _own_chunk_images(ctx, (image for _text, image in sections))
    _own_chunk_images(ctx, (table[0][0] for table in tables))
    tables = enrich_figures(tbls=tables, callback=ctx.callback)
    res = tokenize_table(tables, ctx.doc, ctx.is_english)
    _own_chunk_images(ctx, (item.get("image") for item in res))
    ctx.callback(0.8, "Finish parsing.")
    started = timer()
    chunks, images = naive_merge_docx(
        sections,
        int(ctx.parser_config.get("chunk_token_num", 128)),
        ctx.parser_config.get("delimiter", "\n!?。；！？"),
    )
    _own_chunk_images(ctx, images)
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
    return ChunkBody(res=res)


def _handle_pdf_file(ctx):
    layout_recognizer = ctx.parser_config.get("layout_recognize", "DeepDOC")
    if isinstance(layout_recognizer, bool):
        layout_recognizer = "DeepDOC" if layout_recognizer else "Plain Text"

    from app.infrastructure.model_policy import reject_retired_provider

    parser_name = layout_recognizer.strip().lower()
    reject_retired_provider(parser_name.replace(" ", "_"), capability="parser")
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
    ctx.layout_parser = pdf_parser
    if not sections and not tables:
        return ChunkBody(return_now=True)
    _own_chunk_images(ctx, (table[0][0] for table in tables))
    if parser_name in ["docling", "mineru"]:
        ctx.parser_config["chunk_token_num"] = 0
    res = tokenize_table(tables, ctx.doc, ctx.is_english)
    ctx.callback(0.8, "Finish parsing.")
    return ChunkBody(
        res=res,
        sections=sections,
        pdf_parser=pdf_parser,
    )


def _handle_spreadsheet_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    layout_recognizer = ctx.parser_config.get("layout_recognize", "DeepDOC")
    from app.infrastructure.model_policy import reject_retired_provider

    reject_retired_provider(str(layout_recognizer).strip().lower().replace(" ", "_"), capability="parser")

    excel_parser = ExcelParser()
    if ctx.parser_config.get("html4excel"):
        sections = [(_, "") for _ in excel_parser.parse_html_tables(_parser_source(ctx.filename, ctx.binary), 12) if _]
        ctx.parser_config["chunk_token_num"] = 0
    else:
        sections = [(_, "") for _ in excel_parser.parse_rows(_parser_source(ctx.filename, ctx.binary)) if _]
    return ChunkBody(sections=sections)


def _handle_text_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    sections = parse_text_sections(
        ctx.filename,
        ctx.binary,
        ctx.parser_config.get("chunk_token_num", 128),
        ctx.parser_config.get("delimiter", "\n!?;。；！？"),
    )
    ctx.callback(0.8, "Finish parsing.")
    return ChunkBody(sections=sections)


def _enhance_markdown_sections(sections, section_images, ctx):
    if section_images is None or not any(image is not None for image in section_images):
        return sections, section_images
    try:
        vision_model = VisionCaptionClient()
    except Exception as exc:
        logging.warning("Visual model unavailable; retaining Markdown source: %s", type(exc).__name__)
        return sections, section_images
    pending_error: BaseException | None = None
    try:
        ctx.callback(0.2, "Visual model detected. Attempting to enhance figure extraction...")
        for index, (section_text, section_meta) in enumerate(sections):
            combined_image = section_images[index] if section_images and len(section_images) > index else None
            if combined_image is None:
                continue
            markdown_vision_parser = VisionFigureParser(vision_model=vision_model, figures_data=[(combined_image, [])])
            boosted_figures = markdown_vision_parser(callback=ctx.callback)
            descriptions = [fig[0][1] for fig in boosted_figures if isinstance(fig[0][1], str) and fig[0][1].strip()]
            if descriptions:
                sections[index] = (f"{section_text}\n\n" + "\n\n".join(descriptions), section_meta)
        return sections, section_images
    except BaseException as exc:
        pending_error = exc
        raise
    finally:
        try:
            vision_model.close()
        except BaseException as exc:
            if pending_error is None:
                raise
            pending_error.add_note(f"Markdown vision cleanup failed: {type(exc).__name__}")
            logging.warning("Markdown vision cleanup failed while propagating an error", exc_info=True)


def _handle_markdown_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    markdown_parser = Markdown()
    sections, tables, section_images = markdown_parser(
        ctx.filename,
        ctx.binary,
        separate_tables=False,
        delimiter=ctx.parser_config.get("delimiter", "\n!?;。；！？"),
        return_section_images=True,
    )
    _own_chunk_images(ctx, section_images)
    sections, section_images = _enhance_markdown_sections(sections, section_images, ctx)
    res = tokenize_table(tables, ctx.doc, ctx.is_english)
    ctx.callback(0.8, "Finish parsing.")
    return ChunkBody(
        res=res,
        sections=sections,
        section_images=section_images,
        is_markdown=True,
    )


def _handle_html_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    sections = parse_html_sections(ctx.filename, ctx.binary)
    sections = [(_, "") for _ in sections if _]
    ctx.callback(0.8, "Finish parsing.")
    return ChunkBody(sections=sections)


def _handle_json_file(ctx):
    ctx.callback(0.1, "Start to parse.")
    chunk_token_num = int(ctx.parser_config.get("chunk_token_num", 128))
    binary = Path(ctx.filename).read_bytes() if ctx.binary is None else ctx.binary
    sections = JsonParser(chunk_token_num).split_bytes(binary)
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
        raise RuntimeError("Integrated .doc parsing requires tika")

    with BytesIO(ctx.binary) if ctx.binary is not None else open(ctx.filename, "rb") as source:
        parsed_doc = tika_parser.from_buffer(source)
    if parsed_doc["content"] is None:
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
    if ctx.is_root and ctx.binary is None:
        raise RuntimeError("Embedding extraction from file path is not supported.")
    retained = set()
    with ExitStack() as cleanup:
        cleanup.push(
            lambda _kind, error, _tb: _close_owned_images(
                (image for image_id, image in ctx.owned_images.items() if error is not None and image_id in retained),
                pending_error=error,
            )
        )
        cleanup.push(lambda _kind, error, _tb: close_pdf_parser_images(ctx.layout_parser, pending_error=error))
        cleanup.push(
            lambda _kind, error, _tb: _close_owned_images(
                (
                    image
                    for image_id, image in ctx.owned_images.items()
                    if error is not None or image_id not in retained
                ),
                pending_error=error,
            )
        )
        handler = _resolve_chunk_handler(filename)
        if handler is None:
            raise NotImplementedError("file type not supported yet(pdf, xlsx, doc, docx, txt supported)")

        body = handler(ctx)
        _own_chunk_images(ctx, body.section_images if body.section_images is not None else [])
        _own_chunk_images(ctx, (item.get("image") for item in body.res))
        if body.return_now:
            res = body.res
        else:
            started = timer()
            res = _extend_result_from_sections(body, ctx)
            logging.info("naive_merge(%s): %s", filename, timer() - started)
        _own_chunk_images(ctx, (item.get("image") for item in res))
        if ctx.table_context_size or ctx.image_context_size:
            attach_media_context(res, ctx.table_context_size, ctx.image_context_size)
        retained = {id(item["image"]) for item in res if isinstance(item.get("image"), Image.Image)}
        return res
