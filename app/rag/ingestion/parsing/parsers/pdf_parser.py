# Plain PDF sections include adaptations from InfiniFlow DeepDoc (Apache-2.0); see NOTICE.
"""
PDF parser (based on PyMuPDF).
"""

import logging
from contextlib import ExitStack, closing
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from langchain_core.documents import Document
from PIL import Image as PILImage

from app.rag.ingestion.parsing.enrich.image_understanding import decode_image_codes, infer_visual_kind_from_pixels


def _position_tagged_text(*, page: fitz.Page, page_num: int) -> str:
    blocks: list[str] = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_rest = block
        clean = text.strip()
        if not clean:
            continue
        blocks.append(f"{clean}@@{page_num + 1}\t{float(x0):.1f}\t{float(x1):.1f}\t{float(y0):.1f}\t{float(y1):.1f}##")
    return "\n\n".join(blocks).strip()


def _extract_table_signature(text: str) -> tuple[str, list[str]] | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index in range(len(lines) - 1):
        header = lines[index]
        separator = lines[index + 1]
        if "|" not in header or "|" not in separator:
            continue
        separator_cells = [cell.strip() for cell in separator.strip().strip("|").split("|")]
        if not separator_cells or not all(
            cell and set(cell) <= {"-", ":", " "} and cell.count("-") >= 3 for cell in separator_cells
        ):
            continue
        columns = [cell.strip() for cell in header.strip().strip("|").split("|") if cell.strip()]
        if not columns:
            continue
        return header.strip(), columns
    return None


def _classify_text_page(text: str) -> dict[str, Any]:
    table_signature = _extract_table_signature(text)
    if table_signature is not None:
        header, columns = table_signature
        return {
            "doc_type_kwd": "table",
            "content_type": "table",
            "table_header_present": True,
            "table_header_text": header,
            "table_columns": columns,
        }
    return {}


def _extract_image_payload(*, pdf_document: fitz.Document, xref: int) -> bytes:
    extracted = pdf_document.extract_image(xref)
    image_bytes = extracted.get("image") if isinstance(extracted, dict) else None
    if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        raise ValueError(f"PDF image {xref} has no usable source bytes")
    return bytes(image_bytes)


def _load_rgb_image(image_bytes: bytes) -> PILImage.Image:
    with BytesIO(image_bytes) as source, closing(PILImage.open(source)) as raw_image:
        return raw_image.convert("RGB")


def _decode_image_details(image: PILImage.Image) -> tuple[str, str, list[str]]:
    code_info = decode_image_codes(image)
    visual_kind = code_info.get("visual_kind", "").strip().lower()
    if not visual_kind:
        visual_kind = infer_visual_kind_from_pixels(image).strip().lower()

    code_text = code_info.get("text", "").strip()
    code_values = [item.strip() for item in code_info.get("values", []) if item.strip()]

    return visual_kind, code_text, code_values


def _build_image_document(
    *,
    file_path: Path,
    page_num: int,
    total_pages: int,
    image: PILImage.Image,
    image_index: int,
    visual_kind: str,
    code_text: str,
    code_values: list[str],
) -> Document:
    metadata = {
        "source": file_path.name,
        "page": page_num + 1,
        "total_pages": total_pages,
        "file_type": "pdf",
        "doc_type_kwd": "image",
        "content_type": "image",
        "image": image,
        "image_index": image_index,
    }
    if visual_kind:
        metadata["visual_kind"] = visual_kind
    if code_text:
        metadata["image_code_text"] = code_text
    if code_values:
        metadata["image_code_values"] = code_values

    page_content = code_text or (f"{visual_kind} image" if visual_kind else "")
    return Document(page_content=page_content, metadata=metadata)


def _extract_image_documents(
    *, pdf_document: fitz.Document, page: fitz.Page, file_path: Path, page_num: int, image_resources: ExitStack
) -> list[Document]:
    documents: list[Document] = []
    seen_xrefs: set[int] = set()
    total_pages = len(pdf_document)
    for image_index, image_info in enumerate(page.get_images(full=True)):
        xref = int(image_info[0])
        if xref in seen_xrefs:
            continue
        seen_xrefs.add(xref)
        image_bytes = _extract_image_payload(pdf_document=pdf_document, xref=xref)
        image = _load_rgb_image(image_bytes)
        image_resources.callback(image.close)

        visual_kind, code_text, code_values = _decode_image_details(image)
        documents.append(
            _build_image_document(
                file_path=file_path,
                page_num=page_num,
                total_pages=total_pages,
                image=image,
                image_index=image_index,
                visual_kind=visual_kind,
                code_text=code_text,
                code_values=code_values,
            )
        )
    return documents


class PDFParser:
    """PDF document parser."""

    def parse(self, file_path: Path) -> list[Document]:
        """
        Parse a PDF into a list of LangChain Documents.
        """
        documents: list[Document] = []
        previous_table_signature: tuple[str, list[str]] | None = None

        with ExitStack() as image_resources:
            with fitz.open(str(file_path)) as pdf_document:
                for page_num in range(len(pdf_document)):
                    page = pdf_document[page_num]

                    # Extract text.
                    text = page.get_text()
                    tagged_text = _position_tagged_text(page=page, page_num=page_num)

                    # Image-only pages still carry valuable visual content.
                    if not text.strip():
                        documents.extend(
                            _extract_image_documents(
                                pdf_document=pdf_document,
                                page=page,
                                file_path=file_path,
                                page_num=page_num,
                                image_resources=image_resources,
                            )
                        )
                        continue

                    # Build metadata.
                    metadata = {
                        "source": file_path.name,
                        "page": page_num + 1,
                        "total_pages": len(pdf_document),
                        "file_type": "pdf",
                    }
                    metadata.update(_classify_text_page(text))
                    current_signature = None
                    if metadata.get("doc_type_kwd") == "table":
                        header_text = metadata["table_header_text"]
                        table_columns = list(metadata["table_columns"])
                        current_signature = (header_text, table_columns)
                        if previous_table_signature == current_signature and documents:
                            metadata["table_continued"] = True
                            prev_meta = documents[-1].metadata
                            prev_meta["table_truncated"] = True
                            prev_meta["truncated"] = True
                    previous_table_signature = current_signature

                    # Create Document object.
                    documents.append(
                        Document(
                            page_content=tagged_text or text,
                            metadata=metadata,
                        )
                    )
            # Successful image ownership transfers to returned Document metadata.
            image_resources.pop_all()

        return documents


class PlainPdfParser:
    def __call__(self, filename, from_page=0, to_page=100000, **kwargs):
        from pypdf import PdfReader as pdf2_read

        self.outlines = []
        lines = []
        with open(filename, "rb") if isinstance(filename, str) else BytesIO(filename) as source:
            self.pdf = pdf2_read(source)
            for page in self.pdf.pages[from_page:to_page]:
                lines.extend(list(page.extract_text().split("\n")))

            def dfs(arr, depth):
                for a in arr:
                    if isinstance(a, dict):
                        self.outlines.append((a["/Title"], depth))
                        continue
                    dfs(a, depth + 1)

            try:
                dfs(self.pdf.outline, 0)
            except Exception:
                logging.exception("Outlines exception")
        if not self.outlines:
            logging.warning("Miss outlines")

        return [(line, "") for line in lines], []

    def crop(self, ck, need_position):
        _ = ck
        if need_position:
            return None, None
        return None

    @staticmethod
    def remove_tag(txt):
        return txt
