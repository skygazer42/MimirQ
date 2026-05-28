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

import contextlib
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from os import PathLike
from pathlib import Path
from typing import Any

import pdfplumber
from docling.document_converter import DocumentConverter
from PIL import Image

from app.deepdoc.parser.pdf_parser import IntegratedPipelinePdfParser
from app.rag.core.logging import get_logger

logger = get_logger("deepdoc.parser.docling")


class DoclingContentType(str, Enum):
    IMAGE = "image"
    TABLE = "table"
    TEXT = "text"
    EQUATION = "equation"


@dataclass
class _BBox:
    page_no: int
    x0: float
    y0: float
    x1: float
    y1: float


class JsonReportProcessor:
    """
    Small Docling report assembler.

    Why:
    - keep the legacy `(sections, tables)` contract stable for existing callers
    - expose a structured intermediate payload (`metainfo/content/tables/pictures`)
      so parser behavior becomes easier to inspect and test
    """

    def __init__(self, parser: "DoclingParser") -> None:
        self._parser = parser

    @staticmethod
    def _coerce_page_count(doc: Any) -> int:
        raw = getattr(doc, "num_pages", 0)
        if callable(raw):
            try:
                raw = raw()
            except Exception as exc:
                logger.debug("Ignoring non-critical docling page-count fallback failure: %s", exc)
                raw = 0
        try:
            return max(0, int(raw or 0))
        except Exception:
            return 0

    def _table_entries(self, doc: Any) -> list[tuple[tuple[Any, Any], Any]]:
        rows: list[tuple[tuple[Any, Any], Any]] = []
        for tab in getattr(doc, "tables", []):
            img = None
            positions: Any = ""
            if getattr(tab, "prov", None):
                pn = getattr(tab.prov[0], "page_no", None)
                bb = getattr(tab.prov[0], "bbox", None)
                if pn is not None and bb is not None:
                    left = getattr(bb, "l", None)
                    top = getattr(bb, "t", None)
                    right = getattr(bb, "r", None)
                    bott = getattr(bb, "b", None)
                    if None not in (left, top, right, bott):
                        img, positions = self._parser.cropout_docling_table(
                            int(pn),
                            (float(left), float(top), float(right), float(bott)),
                        )
            html = ""
            try:
                html = tab.export_to_html(doc=doc)
            except Exception as exc:
                logger.debug("Ignoring non-critical docling parser fallback failure: %s", exc)
            rows.append(((img, html), positions if positions else ""))
        return rows

    def _picture_entries(self, doc: Any) -> list[tuple[tuple[Any, Any], Any]]:
        rows: list[tuple[tuple[Any, Any], Any]] = []
        for pic in getattr(doc, "pictures", []):
            img = None
            positions: Any = ""
            if getattr(pic, "prov", None):
                pn = getattr(pic.prov[0], "page_no", None)
                bb = getattr(pic.prov[0], "bbox", None)
                if pn is not None and bb is not None:
                    left = getattr(bb, "l", None)
                    top = getattr(bb, "t", None)
                    right = getattr(bb, "r", None)
                    bott = getattr(bb, "b", None)
                    if None not in (left, top, right, bott):
                        img, positions = self._parser.cropout_docling_table(
                            int(pn),
                            (float(left), float(top), float(right), float(bott)),
                        )
            captions = ""
            try:
                captions = pic.caption_text(doc=doc)
            except Exception as exc:
                logger.debug("Ignoring non-critical docling parser fallback failure: %s", exc)
            rows.append(((img, [captions]), positions if positions else ""))
        return rows

    @staticmethod
    def _page_numbers(doc: Any) -> list[int]:
        pages: set[int] = set()

        def _collect_from_prov(raw: Any) -> None:
            if isinstance(raw, list):
                for item in raw:
                    pn = getattr(item, "page_no", None)
                    if isinstance(pn, int) and pn > 0:
                        pages.add(int(pn))
                return
            pn = getattr(raw, "page_no", None)
            if isinstance(pn, int) and pn > 0:
                pages.add(int(pn))

        for item in getattr(doc, "texts", []) or []:
            _collect_from_prov(getattr(item, "prov", None))
        for item in getattr(doc, "tables", []) or []:
            _collect_from_prov(getattr(item, "prov", None))
        for item in getattr(doc, "pictures", []) or []:
            _collect_from_prov(getattr(item, "prov", None))

        return sorted(pages)

    def build_report(self, doc: Any, *, parse_method: str = "raw") -> dict[str, Any]:
        content = self._parser._transfer_to_sections(doc, parse_method=parse_method)
        tables = self._table_entries(doc)
        pictures = self._picture_entries(doc)

        pages_seen = self._page_numbers(doc)
        missing_pages: list[int] = []
        if pages_seen:
            for page_no in range(min(pages_seen), max(pages_seen) + 1):
                if page_no not in pages_seen:
                    missing_pages.append(int(page_no))

        return {
            "schema": "mimirq.docling_json_report.v1",
            "metainfo": {
                "page_count": self._coerce_page_count(doc),
                "page_continuity": {
                    "pages_seen": pages_seen,
                    "missing_pages": missing_pages,
                    "continuous": not bool(missing_pages),
                },
            },
            "content": list(content),
            "tables": list(tables),
            "pictures": list(pictures),
        }

    @staticmethod
    def to_sections_tables(report: dict[str, Any]) -> tuple[list[Any], list[Any]]:
        payload = dict(report or {})
        return (
            list(payload.get("content") or []),
            list(payload.get("tables") or []) + list(payload.get("pictures") or []),
        )


class DoclingParser(IntegratedPipelinePdfParser):
    def __init__(self):
        self.logger = get_logger("deepdoc.parser.docling.DoclingParser")
        self.page_images: list[Image.Image] = []
        self.page_from = 0
        self.page_to = 10_000
        self.outlines = []


    def check_installation(self) -> bool:
        try:
            _ = DocumentConverter()
            return True
        except Exception as e:
            self.logger.error(f"[Docling] init DocumentConverter failed: {e}")
            return False

    def __images__(self, fnm, zoomin: int = 1, page_from=0, page_to=600, callback=None):
        self.page_from = page_from
        self.page_to = page_to
        pdf = None
        try:
            pdf = pdfplumber.open(fnm) if isinstance(fnm, (str, PathLike)) else pdfplumber.open(BytesIO(fnm))
            pages = pdf.pages[page_from:page_to]
            self.page_images = [p.to_image(resolution=72 * zoomin, antialias=True).original for p in pages]
        except Exception as e:
            self.page_images = []
            self.logger.warning("[Docling] pdfplumber render failed; falling back to PyMuPDF: %s", str(e)[:200])
        finally:
            if pdf is not None:
                pdf.close()

        # Fallback: `pdfplumber.Page.to_image()` may require external render backends (e.g. Poppler),
        # which is often missing in Windows/self-hosted environments. Use PyMuPDF to render page
        # images so figure/table cropping can still work.
        if self.page_images:
            return

        try:
            import fitz  # PyMuPDF
        except ImportError:
            return

        doc = None
        try:
            if isinstance(fnm, (str, PathLike)):
                doc = fitz.open(str(fnm))
            else:
                data = fnm
                if isinstance(data, BytesIO):
                    data = data.getvalue()
                doc = fitz.open(stream=data, filetype="pdf")

            total = int(doc.page_count or 0)
            start = max(0, int(page_from or 0))
            end = min(total, int(page_to or total))
            mat = fitz.Matrix(float(zoomin or 1), float(zoomin or 1))

            rendered: list[Image.Image] = []
            for page_index in range(start, end):
                try:
                    page = doc.load_page(page_index)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    rendered.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
                except Exception:
                    continue

            self.page_images = rendered
        except Exception as e:
            self.page_images = []
            self.logger.warning("[Docling] PyMuPDF render failed: %s", str(e)[:200])
        finally:
            if doc is not None:
                with contextlib.suppress(Exception):
                    doc.close()

    def _make_line_tag(self,bbox: _BBox) -> str:
        if bbox is None:
            return ""
        x0,x1, top, bott = bbox.x0, bbox.x1, bbox.y0, bbox.y1
        if hasattr(self, "page_images") and self.page_images and len(self.page_images) >= bbox.page_no:
            _, page_height = self.page_images[bbox.page_no-1].size
            top, bott = page_height-top ,page_height-bott
        return "@@{}\t{:.1f}\t{:.1f}\t{:.1f}\t{:.1f}##".format(
            bbox.page_no, x0,x1, top, bott
        )

    @staticmethod
    def extract_positions(txt: str) -> list[tuple[list[int], float, float, float, float]]:
        poss = []
        for tag in re.findall(r"@@[0-9-]+\t[0-9.\t]+##", txt):
            pn, left, right, top, bottom = tag.strip("#").strip("@").split("\t")
            left, right, top, bottom = float(left), float(right), float(top), float(bottom)
            poss.append(([int(p) - 1 for p in pn.split("-")], left, right, top, bottom))
        return poss

    def crop(self, text: str, ZM: int = 1, need_position: bool = False):
        imgs = []
        poss = self.extract_positions(text)
        if not poss:
            return (None, None) if need_position else None

        GAP = 6
        pos = poss[0]
        poss.insert(0, ([pos[0][0]], pos[1], pos[2], max(0, pos[3] - 120), max(pos[3] - GAP, 0)))
        pos = poss[-1]
        poss.append(([pos[0][-1]], pos[1], pos[2], min(self.page_images[pos[0][-1]].size[1], pos[4] + GAP), min(self.page_images[pos[0][-1]].size[1], pos[4] + 120)))
        positions = []
        for ii, (pns, left, right, top, bottom) in enumerate(poss):
            if bottom <= top:
                bottom = top + 4
            img0 = self.page_images[pns[0]]
            x0, y0, x1, y1 = int(left), int(top), int(right), int(min(bottom, img0.size[1]))

            crop0 = img0.crop((x0, y0, x1, y1))
            imgs.append(crop0)
            if 0 < ii < len(poss)-1:
                positions.append((pns[0] + self.page_from, x0, x1, y0, y1))
            remain_bottom = bottom - img0.size[1]
            for pn in pns[1:]:
                if remain_bottom <= 0:
                    break
                page = self.page_images[pn]
                x0, y0, x1, y1 = int(left), 0, int(right), int(min(remain_bottom, page.size[1]))
                cimgp = page.crop((x0, y0, x1, y1))
                imgs.append(cimgp)
                if 0 < ii < len(poss) - 1:
                    positions.append((pn + self.page_from, x0, x1, y0, y1))
                remain_bottom -= page.size[1]

        if not imgs:
            return (None, None) if need_position else None

        height = sum(i.size[1] + GAP for i in imgs)
        width = max(i.size[0] for i in imgs)
        pic = Image.new("RGB", (width, int(height)), (245, 245, 245))
        h = 0
        for ii, img in enumerate(imgs):
            if ii == 0 or ii + 1 == len(imgs):
                img = img.convert("RGBA")
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                overlay.putalpha(128)
                img = Image.alpha_composite(img, overlay).convert("RGB")
            pic.paste(img, (0, int(h)))
            h += img.size[1] + GAP

        return (pic, positions) if need_position else pic

    def _iter_doc_items(self, doc) -> Iterable[tuple[str, Any, _BBox | None]]:
        for t in getattr(doc, "texts", []):
            parent=getattr(t, "parent", "")
            ref=getattr(parent,"cref","")
            label=getattr(t, "label", "")
            if (label in ("section_header","text",) and ref in ("#/body",)) or label in ("list_item",):
                text = getattr(t, "text", "") or ""
                bbox = None
                if getattr(t, "prov", None):
                    pn = getattr(t.prov[0], "page_no", None)
                    bb = getattr(t.prov[0], "bbox", None)
                    bb = [getattr(bb, "l", None),getattr(bb, "t", None),getattr(bb, "r", None),getattr(bb, "b", None)]
                    if pn and bb and len(bb) == 4:
                        bbox = _BBox(page_no=int(pn), x0=bb[0], y0=bb[1], x1=bb[2], y1=bb[3])
                yield (DoclingContentType.TEXT.value, text, bbox)

        for item in getattr(doc, "texts", []):
            if getattr(item, "label", "") in ("FORMULA",):
                text = getattr(item, "text", "") or ""
                bbox = None
                if getattr(item, "prov", None):
                    pn = getattr(item.prov, "page_no", None)
                    bb = getattr(item.prov, "bbox", None)
                    bb = [getattr(bb, "l", None),getattr(bb, "t", None),getattr(bb, "r", None),getattr(bb, "b", None)]
                    if pn and bb and len(bb) == 4:
                        bbox = _BBox(int(pn), bb[0], bb[1], bb[2], bb[3])
                yield (DoclingContentType.EQUATION.value, text, bbox)

    def _transfer_to_sections(self, doc, parse_method: str) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        for typ, payload, bbox in self._iter_doc_items(doc):
            if typ == DoclingContentType.TEXT.value:
                section = payload.strip()
                if not section:
                    continue
            elif typ == DoclingContentType.EQUATION.value:
                section = payload.strip()
            else:
                continue

            tag = self._make_line_tag(bbox) if isinstance(bbox,_BBox) else ""
            if parse_method == "manual":
                sections.append((section, typ, tag))
            elif parse_method == "paper":
                sections.append((section + tag, typ))
            else:
                sections.append((section, tag))
        return sections

    def cropout_docling_table(self, page_no: int, bbox: tuple[float, float, float, float], zoomin: int = 1):
        _ = zoomin
        if not getattr(self, "page_images", None):
            return None, ""

        idx = (page_no - 1) - getattr(self, "page_from", 0)
        if idx < 0 or idx >= len(self.page_images):
            return None, ""

        page_img = self.page_images[idx]
        W, H = page_img.size
        left, top, right, bott = bbox

        x0 = float(left)
        y0 = float(H-top)
        x1 = float(right)
        y1 = float(H-bott)

        x0, y0 = max(0.0, min(x0, W - 1)), max(0.0, min(y0, H - 1))
        x1, y1 = max(x0 + 1.0, min(x1, W)), max(y0 + 1.0, min(y1, H))

        try:
            crop = page_img.crop((int(x0), int(y0), int(x1), int(y1))).convert("RGB")
        except Exception:
            return None, ""

        pos = (page_no-1 if page_no>0 else 0, x0, x1, y0, y1)
        return crop, [pos]

    def _transfer_to_tables(self, doc):
        report = JsonReportProcessor(self).build_report(doc, parse_method="raw")
        _sections, tables = JsonReportProcessor.to_sections_tables(report)
        return tables

    def parse_pdf(
        self,
        filepath: str | PathLike[str],
        binary: BytesIO | bytes | None = None,
        callback: Callable | None = None,
        *,
        output_dir: str | None = None,
        lang: str | None = None,
        method: str = "auto",
        delete_output: bool = True,
        parse_method: str = "raw"
    ):
        _ = (lang, method)

        if not self.check_installation():
            raise RuntimeError("Docling not available, please install `docling`")

        if binary is not None:
            tmpdir = Path(output_dir) if output_dir else Path.cwd() / ".docling_tmp"
            tmpdir.mkdir(parents=True, exist_ok=True)
            name = Path(filepath).name or "input.pdf"
            tmp_pdf = tmpdir / name
            with open(tmp_pdf, "wb") as f:
                if isinstance(binary, (bytes, bytearray)):
                    f.write(binary)
                else:
                    f.write(binary.getbuffer())
            src_path = tmp_pdf
        else:
            src_path = Path(filepath)
            if not src_path.exists():
                raise FileNotFoundError(f"PDF not found: {src_path}")

        if callback:
            callback(0.1, f"[Docling] Converting: {src_path}")

        try:
            self.__images__(str(src_path), zoomin=1)
        except Exception as e:
            self.logger.warning(f"[Docling] render pages failed: {e}")

        conv = DocumentConverter()
        conv_res = conv.convert(str(src_path))
        doc = conv_res.document
        if callback:
            callback(0.7, f"[Docling] Parsed doc: {getattr(doc, 'num_pages', 'n/a')} pages")

        report = JsonReportProcessor(self).build_report(doc, parse_method=parse_method)
        sections, tables = JsonReportProcessor.to_sections_tables(report)

        if callback:
            callback(0.95, f"[Docling] Sections: {len(sections)}, Tables: {len(tables)}")

        if binary is not None and delete_output:
            try:
                Path(src_path).unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("Ignoring non-critical docling parser fallback failure: %s", exc)

        if callback:
            callback(1.0, "[Docling] Done.")
        return sections, tables


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = DoclingParser()
    logging.info("Docling available: %s", parser.check_installation())
    sections, tables = parser.parse_pdf(filepath="test_docling/toc.pdf", binary=None)
    logging.info("%s sections, %s tables", len(sections), len(tables))
