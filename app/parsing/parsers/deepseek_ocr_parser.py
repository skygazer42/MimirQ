"""
DeepSeek OCR parser (SiliconFlow API).

This backend converts PDF pages into images and uses DeepSeek-OCR to return
Markdown. Intended for scanned PDFs or image-heavy documents.
"""

from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from typing import List

import fitz  # PyMuPDF
import requests
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.logging import get_logger


logger = get_logger("parsing.deepseek_ocr")


_TAG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<\|ref\|>.*?<\|/ref\|>", re.DOTALL),
    re.compile(r"<\|det\|>.*?<\|/det\|>", re.DOTALL),
)


class DeepSeekOCRParser:
    """
    DeepSeek OCR parser via SiliconFlow (OpenAI-compatible chat completions).

    Config via env/.env:
    - DEEPSEEK_OCR_ENABLED=true
    - SILICONFLOW_API_KEY=...
    - SILICONFLOW_API_BASE=https://api.siliconflow.cn/v1
    - DEEPSEEK_OCR_MODEL=deepseek-ai/DeepSeek-OCR
    """

    def __init__(self) -> None:
        self._api_key = (getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip()
        self._api_base = (getattr(settings, "SILICONFLOW_API_BASE", "") or "https://api.siliconflow.cn/v1").strip()
        self._model = (getattr(settings, "DEEPSEEK_OCR_MODEL", "") or "deepseek-ai/DeepSeek-OCR").strip()

        self._timeout_sec = float(getattr(settings, "DEEPSEEK_OCR_TIMEOUT_SEC", 120) or 120)
        self._max_tokens = int(getattr(settings, "DEEPSEEK_OCR_MAX_TOKENS", 4096) or 4096)
        self._temperature = float(getattr(settings, "DEEPSEEK_OCR_TEMPERATURE", 0.1) or 0.1)
        self._pdf_dpi = int(getattr(settings, "DEEPSEEK_OCR_PDF_DPI", 200) or 200)

        base = self._api_base.rstrip("/")
        # Allow users to pass either ".../v1" or the full ".../v1/chat/completions".
        self._api_url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"

        if not self._api_key:
            raise RuntimeError(
                "DeepSeek OCR requires SILICONFLOW_API_KEY. "
                "Set DEEPSEEK_OCR_ENABLED=true and configure SILICONFLOW_API_KEY."
            )

        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    def parse(self, file_path: Path) -> List[Document]:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if file_path.suffix.lower() != ".pdf":
            raise ValueError("DeepSeek OCR currently supports PDF only")

        start = time.time()
        logger.info("[deepseek_ocr] start %s", file_path.name)

        doc = fitz.open(str(file_path))
        try:
            total_pages = int(len(doc))
            parts: list[str] = []

            for idx, page in enumerate(doc, start=1):
                pix = page.get_pixmap(dpi=self._pdf_dpi)
                img_bytes = pix.tobytes("png")
                logger.info("[deepseek_ocr] page %s/%s (%s)", idx, total_pages, file_path.name)
                text = self._call_api(img_bytes, mime_type="image/png")
                if text:
                    parts.append(text)

            merged = "\n\n".join(p.strip() for p in parts if p and p.strip()).strip()
            meta = {
                "source": file_path.name,
                "file_type": "pdf",
                "total_pages": total_pages,
                "parser_backend": "deepseek_ocr",
            }
            logger.info("[deepseek_ocr] done %s in %.2fs", file_path.name, time.time() - start)
            return [Document(page_content=merged, metadata=meta)]
        finally:
            doc.close()

    def _call_api(self, data_bytes: bytes, *, mime_type: str) -> str:
        encoded = base64.b64encode(data_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{encoded}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {
                        "type": "text",
                        "text": "<image>\n<|grounding|>Convert the document to markdown.",
                    },
                ],
            }
        ]

        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }

        resp = requests.post(self._api_url, headers=self._headers, json=payload, timeout=self._timeout_sec)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise RuntimeError(f"DeepSeek OCR API error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        text = str(content).strip()
        for pattern in _TAG_PATTERNS:
            text = pattern.sub("", text)
        return text.strip()

