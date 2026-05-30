"""
RapidOCR service for PDF quality evaluation and scan detection.

Lightweight wrapper around RapidOCR (PP-OCRv4), used only for sampling
the first few pages.
"""

import tempfile
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from PIL import Image

from app.rag.core.logging import get_logger

logger = get_logger("parsing.quality.ocr")


class RapidOCRService:
    """RapidOCR service (lazy init)."""

    def __init__(self, det_box_thresh: float = 0.3):
        self._ocr: Any | None = None
        self.det_box_thresh = det_box_thresh

    def _load_model(self):
        """Lazy-load OCR model."""
        if self._ocr is not None:
            return

        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            self._ocr = RapidOCR(det_box_thresh=self.det_box_thresh)
            logger.info("RapidOCR model loaded (det_box_thresh=%s)", self.det_box_thresh)
        except ImportError as e:
            raise RuntimeError(
                "RapidOCR is not installed. Install `rapidocr-onnxruntime` (and its runtime deps) "
                "or set RAPIDOCR_ENABLED=false."
            ) from e
        except Exception as e:
            raise RuntimeError(f"Failed to load RapidOCR model: {e}") from e

    def ocr_pdf_pages(
        self,
        pdf_path: Path,
        max_pages: int = 3,
        zoom_x: float = 2.0,
        zoom_y: float = 2.0
    ) -> tuple[str, int]:
        """
        Run OCR on the first few PDF pages and return text + total chars.

        Args:
            pdf_path: PDF file path.
            max_pages: Max pages to process.
            zoom_x/zoom_y: Render scale (increase clarity).

        Returns:
            (ocr_text, char_count)
        """
        self._load_model()

        all_text = []
        total_chars = 0

        try:
            with fitz.open(str(pdf_path)) as pdf_doc:
                pages_to_process = min(max_pages, pdf_doc.page_count)

                for page_num in range(pages_to_process):
                    page = pdf_doc[page_num]

                    # Convert to image.
                    mat = fitz.Matrix(zoom_x, zoom_y)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img_pil = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                    # OCR recognition.
                    text = self._ocr_image(img_pil)
                    all_text.append(text)
                    total_chars += len(text)

            combined_text = "\n\n".join(all_text)
            return combined_text, total_chars

        except Exception as e:
            logger.warning("RapidOCR PDF processing failed: %s", e)
            return "", 0

    def ocr_image(self, image: Image.Image) -> str:
        """Run OCR on a single PIL image (best-effort)."""
        self._load_model()
        return self._ocr_image(image)

    def _ocr_image(self, image: Image.Image) -> str:
        """Run OCR on a single image."""
        if self._ocr is None:
            return ""

        text = ""
        try:
            # Save to temp file (RapidOCR requires a file path).
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                image.save(tmp_path)

            try:
                result, _ = self._ocr(str(tmp_path))
                if result:
                    text = "\n".join([line[1] for line in result])
            finally:
                # Clean up temp file.
                if tmp_path.exists():
                    tmp_path.unlink()

        except Exception as e:
            logger.warning("RapidOCR image OCR failed: %s", e)
        return text


# Global instance (lazy init).
rapid_ocr_service = RapidOCRService()
