"""
RapidOCR 服务 - 用于 PDF 质量评估和扫描件识别

轻量封装 RapidOCR (PP-OCRv4)，仅用于前几页的采样检测。
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image

from rapidocr_onnxruntime import RapidOCR


class RapidOCRService:
    """RapidOCR 服务（延迟加载）"""

    def __init__(self, det_box_thresh: float = 0.3):
        self._ocr: Optional[RapidOCR] = None
        self.det_box_thresh = det_box_thresh

    def _load_model(self):
        """延迟加载 OCR 模型"""
        if self._ocr is not None:
            return

        try:
            self._ocr = RapidOCR(det_box_thresh=self.det_box_thresh)
            print(f"[RapidOCR] 模型加载成功 (det_box_thresh={self.det_box_thresh})")
        except Exception as e:
            raise RuntimeError(f"RapidOCR 模型加载失败: {e}") from e

    def ocr_pdf_pages(
        self,
        pdf_path: Path,
        max_pages: int = 3,
        zoom_x: float = 2.0,
        zoom_y: float = 2.0
    ) -> Tuple[str, int]:
        """
        对 PDF 前几页做 OCR，返回识别文本和总字符数。

        Args:
            pdf_path: PDF 文件路径
            max_pages: 最多处理的页数
            zoom_x/zoom_y: 渲染缩放比例（提高清晰度）

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

                    # 转为图像
                    mat = fitz.Matrix(zoom_x, zoom_y)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img_pil = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                    # OCR 识别
                    text = self._ocr_image(img_pil)
                    all_text.append(text)
                    total_chars += len(text)

            combined_text = "\n\n".join(all_text)
            return combined_text, total_chars

        except Exception as e:
            print(f"[WARN] RapidOCR PDF 处理失败: {e}")
            return "", 0

    def _ocr_image(self, image: Image.Image) -> str:
        """对单张图像做 OCR"""
        if self._ocr is None:
            return ""

        try:
            # 保存到临时文件（RapidOCR 需要文件路径）
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                image.save(tmp_path)

            try:
                result, _ = self._ocr(str(tmp_path))
                if result:
                    return "\n".join([line[1] for line in result])
                return ""
            finally:
                # 清理临时文件
                if tmp_path.exists():
                    tmp_path.unlink()

        except Exception as e:
            print(f"[WARN] RapidOCR 图像识别失败: {e}")
            return ""


# 全局实例（延迟初始化）
rapid_ocr_service = RapidOCRService()

