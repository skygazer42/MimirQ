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
    base = (api_base or "").strip().rstrip("/")
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

    def __init__(self, tenant_id: str, llm_type: str, **kwargs: Any):
        self.tenant_id = tenant_id
        self.llm_type = str(llm_type)
        self.kwargs = dict(kwargs or {})

        if str(llm_type) != str(LLMType.IMAGE2TEXT):
            raise NotImplementedError(
                f"LLMBundle only supports {LLMType.IMAGE2TEXT} in this project; got: {llm_type}"
            )

        if not bool(getattr(settings, "VISION_LLM_ENABLED", False)):
            raise NotImplementedError(
                "Vision enrichment is disabled. Set MIMIRQ_VISION_LLM_ENABLED=true to enable image-to-text parsing."
            )

        api_key = (getattr(settings, "VISION_LLM_API_KEY", "") or "").strip() or (
            getattr(settings, "LLM_API_KEY", "") or ""
        ).strip()
        api_base = (getattr(settings, "VISION_LLM_API_BASE", "") or "").strip() or (
            getattr(settings, "LLM_API_BASE", "") or ""
        ).strip()

        # Integrated pipeline passes llm_name for user-selected layout recognizer model; treat as model override.
        model = (self.kwargs.get("llm_name") or getattr(settings, "VISION_LLM_MODEL", "") or "").strip()

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

        self._timeout_sec = float(getattr(settings, "VISION_LLM_TIMEOUT_SEC", 120) or 120)
        self._max_tokens = int(getattr(settings, "VISION_LLM_MAX_TOKENS", 4096) or 4096)
        self._temperature = float(getattr(settings, "VISION_LLM_TEMPERATURE", 0.0) or 0.0)

        self._session = requests.Session()
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, *, image_bytes: bytes, prompt: str | None) -> dict[str, Any]:
        mime_type = _guess_mime_type(image_bytes)
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{encoded}"

        # Put instructions first for better determinism across providers.
        content = []
        if prompt:
            content.append({"type": "text", "text": str(prompt)})
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
        if image_bytes is None:
            raise ValueError("image_bytes is required")

        payload = self._build_payload(image_bytes=image_bytes, prompt=prompt)
        resp = self._session.post(
            self._api_url,
            headers=self._headers,
            json=payload,
            timeout=self._timeout_sec,
        )

        if int(getattr(resp, "status_code", 0) or 0) != 200:
            body = getattr(resp, "text", "") or ""
            logger.warning("Integrated pipeline vision API error %s: %s", getattr(resp, "status_code", None), body[:500])
            raise RuntimeError(f"Integrated pipeline vision API error {resp.status_code}: {body[:500]}")

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return str(content or "").strip()
