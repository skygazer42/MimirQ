# Adapted from InfiniFlow RAGFlow (Apache-2.0); see NOTICE.
"""Synchronous image captions and shared OpenAI-compatible image content."""

import base64
import logging
from typing import Any, Literal, TypedDict
from weakref import finalize

import requests

from app.infrastructure.config import settings

logger = logging.getLogger("integrated.llm_service")


class VisionImageBlock(TypedDict):
    type: Literal["image_url"]
    image_url: dict[str, str]


def _guess_mime_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def build_image_url_block(image_bytes: bytes) -> VisionImageBlock:
    """Encode image bytes using their recognized MIME type, defaulting to JPEG."""
    mime_type = _guess_mime_type(image_bytes)
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}}


def _chat_completions_url(api_base: str) -> str:
    base = api_base.strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


class VisionCaptionClient:
    """Own a captioning session; unavailable configuration raises NotImplementedError.

    Parsing callers retain their existing plaintext fallback. Explicit close and
    collection both release this client's pooled connections.
    """

    def __init__(self, *, model_name: str | None = None) -> None:
        if not settings.VISION_LLM_ENABLED:
            raise NotImplementedError(
                "Vision enrichment is disabled. Set MIMIRQ_VISION_LLM_ENABLED=true to enable image-to-text parsing."
            )

        api_key = settings.VISION_LLM_API_KEY.strip() or settings.LLM_API_KEY.strip()
        api_base = settings.VISION_LLM_API_BASE.strip() or settings.LLM_API_BASE.strip()
        model = (model_name or settings.VISION_LLM_MODEL).strip()

        if not api_key:
            raise NotImplementedError(
                "Vision enrichment requires an API key. Set MIMIRQ_VISION_LLM_API_KEY (or LLM_API_KEY)."
            )
        if not api_base:
            raise NotImplementedError(
                "Vision enrichment requires an API base. Set MIMIRQ_VISION_LLM_API_BASE (or LLM_API_BASE)."
            )
        if not model:
            raise NotImplementedError(
                "Vision enrichment requires a model. Set MIMIRQ_VISION_LLM_MODEL (or pass model_name)."
            )

        self._api_url = _chat_completions_url(api_base)
        self._model = model
        self._timeout_sec = settings.VISION_LLM_TIMEOUT_SEC
        self._max_tokens = settings.VISION_LLM_MAX_TOKENS
        self._temperature = settings.VISION_LLM_TEMPERATURE

        self._session = requests.Session()
        self._close_session = finalize(self, self._session.close)
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def close(self) -> None:
        self._close_session()

    def _build_payload(self, *, image_bytes: bytes, prompt: str | None) -> dict[str, Any]:
        content: list[dict[str, Any] | VisionImageBlock] = []
        if prompt:
            content.append({"type": "text", "text": prompt})
        content.append(build_image_url_block(image_bytes))

        return {
            "model": self._model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "stream": False,
        }

    def describe_with_prompt(self, image_bytes: bytes, prompt: str | None = None) -> str:
        """Return a text caption, propagating request and response errors to the caller."""
        if not self._close_session.alive:
            raise RuntimeError("VisionCaptionClient is closed")

        payload = self._build_payload(image_bytes=image_bytes, prompt=prompt)
        with self._session.post(
            self._api_url,
            headers=self._headers,
            json=payload,
            timeout=self._timeout_sec,
        ) as response:
            if response.status_code != 200:
                body = response.text[:500]
                logger.warning("Integrated pipeline vision API error %s: %s", response.status_code, body)
                raise RuntimeError(f"Integrated pipeline vision API error {response.status_code}: {body}")

            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("Vision response must be an object")
            content = data["choices"][0]["message"]["content"]
            if content is None:
                return ""
            if not isinstance(content, str):
                raise TypeError("Vision response content must be text")
            return content.strip()


__all__ = ["VisionCaptionClient", "VisionImageBlock", "build_image_url_block"]
