from __future__ import annotations

from typing import Any

from app.core.config import settings

_CACHE_CONTROL = {"type": "ephemeral"}


def detect_anthropic_compatible(*, model_name: str, base_url: str) -> bool:
    model_lower = str(model_name or "").strip().lower()
    base_lower = str(base_url or "").strip().lower()
    return model_lower.startswith("claude") or ("anthropic" in base_lower)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").strip().lower() != "text":
                continue
            parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return str(content or "")


def should_cache_message(*, role: str, content: Any, anthropic_compatible: bool) -> bool:
    if not bool(getattr(settings, "PROMPT_CACHE_ENABLED", False)):
        return False
    if not bool(anthropic_compatible):
        return False
    role_norm = str(role or "").strip().lower()
    if role_norm in {"system", "developer"}:
        return True
    min_chars = int(getattr(settings, "PROMPT_CACHE_MIN_CHARS", 1000) or 1000)
    return len(_content_text(content)) >= max(0, min_chars)


def annotate_prompt_cache_content(*, role: str, content: Any, anthropic_compatible: bool) -> tuple[Any, bool]:
    if not should_cache_message(role=role, content=content, anthropic_compatible=anthropic_compatible):
        return content, False

    if isinstance(content, list):
        annotated: list[Any] = []
        applied = False
        for item in content:
            if isinstance(item, dict) and str(item.get("type") or "").strip().lower() == "text":
                updated = dict(item)
                if not isinstance(updated.get("cache_control"), dict):
                    updated["cache_control"] = dict(_CACHE_CONTROL)
                annotated.append(updated)
                applied = True
            else:
                annotated.append(item)
        if applied:
            return annotated, True

    return [{"type": "text", "text": _content_text(content), "cache_control": dict(_CACHE_CONTROL)}], True


def annotate_openai_messages_for_prompt_cache(
    *,
    messages: list[dict[str, Any]],
    anthropic_compatible: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    annotated_messages: list[dict[str, Any]] = []
    applied_count = 0

    for message in messages:
        cloned = dict(message)
        annotated_content, applied = annotate_prompt_cache_content(
            role=str(cloned.get("role") or ""),
            content=cloned.get("content"),
            anthropic_compatible=anthropic_compatible,
        )
        cloned["content"] = annotated_content
        if applied:
            applied_count += 1
        annotated_messages.append(cloned)

    return annotated_messages, {
        "prompt_cache_applied": bool(applied_count),
        "prompt_cache_message_count": int(applied_count),
        "provider_anthropic_compatible": bool(anthropic_compatible),
    }
