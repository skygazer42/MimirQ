"""
PDF parser (based on PyMuPDF).
"""
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from langchain_core.documents import Document
from PIL import Image as PILImage

from app.core.constants import NON_CRITICAL_EXCEPTION_LOG_MESSAGE
from app.parsing.enrich.image_understanding import decode_image_codes, infer_visual_kind_from_pixels
from app.rag.core.logging import get_logger


class PDFParser:
    """PDF document parser."""

    def _position_tagged_text(self, *, page, page_num: int) -> str:  # noqa: ANN001
        blocks: list[str] = []
        for block in page.get_text("blocks") or []:
            try:
                x0, y0, x1, y1, text, *_rest = block
            except Exception:
                get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                continue
            clean = str(text or "").strip()
            if not clean:
                continue
            blocks.append(
                f"{clean}@@{int(page_num) + 1}\t{float(x0):.1f}\t{float(x1):.1f}\t{float(y0):.1f}\t{float(y1):.1f}##"
            )
        return "\n\n".join(blocks).strip()

    def _extract_table_signature(self, text: str) -> tuple[str, list[str]] | None:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        for index in range(len(lines) - 1):
            header = lines[index]
            separator = lines[index + 1]
            if "|" not in header or "|" not in separator:
                continue
            separator_cells = [cell.strip() for cell in separator.strip().strip("|").split("|")]
            if not separator_cells or not all(
                cell and set(cell) <= {"-", ":", " "} and cell.count("-") >= 3
                for cell in separator_cells
            ):
                continue
            columns = [cell.strip() for cell in header.strip().strip("|").split("|") if cell.strip()]
            if not columns:
                continue
            return header.strip(), columns
        return None

    def _classify_text_page(self, text: str) -> dict[str, Any]:
        table_signature = self._extract_table_signature(text)
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

    def _extract_image_payload(self, *, pdf_document, xref: int) -> bytes | None:  # noqa: ANN001
        try:
            extracted = pdf_document.extract_image(xref)
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            return None
        image_bytes = extracted.get("image") if isinstance(extracted, dict) else None
        if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
            return None
        return bytes(image_bytes)

    def _load_rgb_image(self, image_bytes: bytes):  # noqa: ANN001
        try:
            with PILImage.open(BytesIO(image_bytes)) as raw_image:
                return raw_image.convert("RGB")
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            return None

    def _decode_image_details(self, image) -> tuple[str, str, list[str]]:  # noqa: ANN001
        code_info = decode_image_codes(image)
        visual_kind = str(code_info.get("visual_kind") or "").strip().lower() if isinstance(code_info, dict) else ""
        if not visual_kind:
            visual_kind = str(infer_visual_kind_from_pixels(image) or "").strip().lower()

        code_text = str(code_info.get("text") or "").strip() if isinstance(code_info, dict) else ""
        code_values: list[str] = []
        if isinstance(code_info, dict):
            raw_values = code_info.get("values")
            if isinstance(raw_values, list):
                code_values = [str(item).strip() for item in raw_values if str(item).strip()]

        return visual_kind, code_text, code_values

    def _build_image_document(
        self,
        *,
        file_path: Path,
        page_num: int,
        total_pages: int,
        image,
        image_index: int,
        visual_kind: str,
        code_text: str,
        code_values: list[str],
    ) -> Document:
        metadata = {
            "source": str(file_path.name),
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

    def _extract_image_documents(self, *, pdf_document, page, file_path: Path, page_num: int) -> list[Document]:  # noqa: ANN001
        documents: list[Document] = []
        seen_xrefs: set[int] = set()
        total_pages = len(pdf_document)
        for image_index, image_info in enumerate(page.get_images(full=True) or []):
            try:
                xref = int(image_info[0])
            except Exception:
                get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                continue
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            image_bytes = self._extract_image_payload(pdf_document=pdf_document, xref=xref)
            if image_bytes is None:
                continue
            image = self._load_rgb_image(image_bytes)
            if image is None:
                continue

            visual_kind, code_text, code_values = self._decode_image_details(image)
            documents.append(
                self._build_image_document(
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

    def parse(self, file_path: Path) -> list[Document]:
        """
        Parse a PDF into a list of LangChain Documents.
        """
        documents: list[Document] = []
        previous_table_signature: tuple[str, list[str]] | None = None

        # Open PDF file.
        pdf_document = fitz.open(str(file_path))

        try:
            for page_num in range(len(pdf_document)):
                page = pdf_document[page_num]

                # Extract text.
                text = page.get_text()
                tagged_text = self._position_tagged_text(page=page, page_num=page_num)

                # Image-only pages still carry valuable visual content.
                if not text.strip():
                    documents.extend(
                        self._extract_image_documents(
                            pdf_document=pdf_document,
                            page=page,
                            file_path=file_path,
                            page_num=page_num,
                        )
                    )
                    continue

                # Build metadata.
                metadata = {
                    "source": str(file_path.name),
                    "page": page_num + 1,
                    "total_pages": len(pdf_document),
                    "file_type": "pdf",
                }
                metadata.update(self._classify_text_page(text))
                current_signature = None
                if str(metadata.get("doc_type_kwd") or "").strip().lower() == "table":
                    header_text = str(metadata.get("table_header_text") or "").strip()
                    table_columns = list(metadata.get("table_columns") or [])
                    current_signature = (header_text, table_columns)
                    if previous_table_signature == current_signature and documents:
                        metadata["table_continued"] = True
                        prev_meta = documents[-1].metadata if isinstance(documents[-1].metadata, dict) else None
                        if isinstance(prev_meta, dict):
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

        finally:
            pdf_document.close()

        return documents
