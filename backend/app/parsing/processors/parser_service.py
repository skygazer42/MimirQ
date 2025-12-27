"""
统一文档解析入口：
- 按文件类型分流（office → MarkItDown；PDF → 评分后选择 MarkItDown / DeepDoc / MinerU / basic）
- 提取 Markdown、图片落盘并返回预览
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID
import base64
import re
import uuid

from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.factory import parser_factory
from app.parsing.routing import route_pdf_backend


class DocumentParserService:
    def __init__(self):
        pass

    def parse_for_preview(
        self,
        file_path: Path,
        tenant_id: UUID,
        parser_backend: Optional[str] = None,
    ) -> Dict:
        """
        解析文件，返回 Markdown 与图片清单，不入库。
        """
        file_ext = file_path.suffix.lower()
        is_pdf = file_ext == ".pdf"
        pdf_quality = None

        # PDF 评分并选择解析器
        if is_pdf:
            parser_backend, pdf_quality = route_pdf_backend(
                file_path,
                parser_backend,
                sample_pages=3,
                use_ocr_validation=settings.RAPIDOCR_ENABLED,
            )
        else:
            # 非 PDF 强制走 MarkItDown（office/表格），或文本解析
            parser_backend = parser_backend or "markitdown"

        documents, resolved_backend = parser_factory.parse(file_path, parser_backend=parser_backend)
        markdown_text = self._merge_documents(documents)

        images = self._extract_and_save_inline_images(markdown_text, tenant_id)
        if images:
            # 将 data URI 替换为本地引用
            for img in images:
                markdown_text = markdown_text.replace(img["original"], img["markdown_ref"])

        return {
            "backend": resolved_backend,
            "pdf_quality": pdf_quality,
            "markdown": markdown_text,
            "images": [
                {
                    "id": img["id"],
                    "url": img["url"],
                    "filename": img["filename"],
                }
                for img in images
            ],
        }

    def _merge_documents(self, documents: List[Document]) -> str:
        parts = []
        for doc in documents:
            text = doc.page_content or ""
            parts.append(text.strip())
        return "\n\n".join(p for p in parts if p)

    def _extract_and_save_inline_images(self, markdown_text: str, tenant_id: UUID) -> List[Dict]:
        """
        查找 data URI 图片，落盘到 uploads/{tenant_id}/images，并返回映射信息。
        """
        images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        pattern = re.compile(r"!\[[^\]]*\]\((data:image\/[a-zA-Z0-9+\/;=,:.-]+)\)")
        matches = list(pattern.finditer(markdown_text))

        saved = []
        for m in matches:
            data_uri = m.group(1)
            img_id = uuid.uuid4().hex
            filename = f"{img_id}.png"
            file_path = images_dir / filename

            try:
                b64_part = data_uri.split("base64,")[-1]
                binary = base64.b64decode(b64_part)
                file_path.write_bytes(binary)
            except Exception:
                continue

            markdown_ref = f"![image]({file_path.name})"
            saved.append(
                {
                    "id": img_id,
                    "filename": filename,
                    "path": str(file_path),
                    "url": f"/api/v1/documents/image/{img_id}",
                    "original": data_uri,
                    "markdown_ref": markdown_ref,
                }
            )

        return saved


document_parser_service = DocumentParserService()
