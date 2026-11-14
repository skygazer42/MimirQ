"""
Integrated pipeline LLMBundle adapter.

Upstream Integrated pipeline uses a set of internal service APIs ("LLMBundle") to access
tenant-scoped LLM services. MimirQ does not ship the full Integrated pipeline backend,
but we still want to enable the "vision-based" chunking helpers when a user
explicitly configures a VLM via `.env`.

This module implements the minimal surface used by the integrated chunkers:
- IMAGE2TEXT: `describe_with_prompt(image_bytes, prompt) -> str`

When not configured, this class raises NotImplementedError so callers can
fail-soft and fall back to plaintext parsing (see `integrated/chunkers/naive.py`).
"""

import base64
from typing import Any
from weakref import finalize

import requests

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.third_party.integrated_pipeline.common.constants import LLMType

logger = get_logger("integrated.llm_service")


def _guess_mime_type(image_bytes: bytes) -> str:
    if not image_bytes:
        return "image/jpeg"
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    # JPEG: FF D8 FF
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    # GIF: GIF87a / GIF89a
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    # WebP: RIFF....WEBP
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _chat_completions_url(api_base: str) -> str:
    base = api_base.strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


class LLMBundle:
    """
    Minimal LLMBundle implementation for Integrated pipeline-integrated chunkers.

    Notes:
    - Only IMAGE2TEXT is supported in this repo.
    - When disabled/misconfigured, raises NotImplementedError so callers can
      gracefully fall back (the chunkers already wrap this in try/except).
    """

    def __init__(self, tenant_id: str, llm_type: str, **kwargs: Any) -> None:
        self.tenant_id = tenant_id
        self.llm_type = str(llm_type)
        self.kwargs = dict(kwargs)

        if str(llm_type) != str(LLMType.IMAGE2TEXT):
            raise NotImplementedError(f"LLMBundle only supports {LLMType.IMAGE2TEXT} in this project; got: {llm_type}")

        if not settings.VISION_LLM_ENABLED:
            raise NotImplementedError(
                "Vision enrichment is disabled. Set MIMIRQ_VISION_LLM_ENABLED=true to enable image-to-text parsing."
            )

        api_key = settings.VISION_LLM_API_KEY.strip() or settings.LLM_API_KEY.strip()
        api_base = settings.VISION_LLM_API_BASE.strip() or settings.LLM_API_BASE.strip()

        # Integrated pipeline passes llm_name for user-selected layout recognizer model; treat as model override.
        model = (self.kwargs.get("llm_name") or settings.VISION_LLM_MODEL).strip()

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
                "Vision enrichment requires a model. Set MIMIRQ_VISION_LLM_MODEL (or pass llm_name)."
            )

        self._api_url = _chat_completions_url(api_base)
        self._api_key = api_key
        self._model = model

        self._timeout_sec = settings.VISION_LLM_TIMEOUT_SEC
        self._max_tokens = settings.VISION_LLM_MAX_TOKENS
        self._temperature = settings.VISION_LLM_TEMPERATURE

        self._session = requests.Session()
        # Fixed upstream callers do not expose a close hook; collection still
        # releases this instance's pooled connections without retaining self.
        self._close_session = finalize(self, self._session.close)
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def close(self) -> None:
        self._close_session()

    def _build_payload(self, *, image_bytes: bytes, prompt: str | None) -> dict[str, Any]:
        mime_type = _guess_mime_type(image_bytes)
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{encoded}"

        # Put instructions first for better determinism across providers.
        content = []
        if prompt:
            content.append({"type": "text", "text": prompt})
        content.append({"type": "image_url", "image_url": {"url": data_url}})

        return {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "stream": False,
        }

    def describe_with_prompt(self, image_bytes: bytes, prompt: str | None = None) -> str:
        """
        Describe an image with an explicit prompt (image -> markdown/text).

        This mirrors what DeepDoc's VisionParser expects.
        """
        if not self._close_session.alive:
            raise RuntimeError("LLMBundle is closed")

        payload = self._build_payload(image_bytes=image_bytes, prompt=prompt)
        with self._session.post(
            self._api_url,
            headers=self._headers,
            json=payload,
            timeout=self._timeout_sec,
        ) as response:
            if response.status_code != 200:
                body = response.text
                logger.warning("Integrated pipeline vision API error %s: %s", response.status_code, body[:500])
                raise RuntimeError(f"Integrated pipeline vision API error {response.status_code}: {body[:500]}")

            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("Vision response must be an object")
            content = data["choices"][0]["message"]["content"]
            if content is None:
                return ""
            if not isinstance(content, str):
                raise TypeError("Vision response content must be text")
            return content.strip()
