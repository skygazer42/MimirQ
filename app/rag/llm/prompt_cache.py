from typing import Any, TypedDict

from app.core.config import settings

_CACHE_CONTROL = {"type": "ephemeral"}


class PromptCacheMetadata(TypedDict):
    prompt_cache_applied: bool
    prompt_cache_message_count: int
    provider_anthropic_compatible: bool


def detect_anthropic_compatible(*, model_name: str, base_url: str | None) -> bool:
    model_lower = model_name.strip().lower()
    base_lower = base_url.strip().lower() if base_url is not None else None
    return model_lower.startswith("claude") or (base_lower is not None and "anthropic" in base_lower)


def message_content_to_text(content: Any) -> str | None:
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
            if item.get("type") != "text":
                continue
            parts.append(item["text"])
        return "".join(parts)
    return str(content) if content is not None else None


def should_cache_message(*, role: str, content: Any, anthropic_compatible: bool) -> bool:
    if content is None or not settings.PROMPT_CACHE_ENABLED:
        return False
    if not bool(anthropic_compatible):
        return False
    role_norm = role.strip().lower()
    if role_norm in {"system", "developer"}:
        return True
    min_chars = settings.PROMPT_CACHE_MIN_CHARS
    return len(message_content_to_text(content)) >= max(0, min_chars)


def annotate_prompt_cache_content(*, role: str, content: Any, anthropic_compatible: bool) -> tuple[Any, bool]:
    if not should_cache_message(role=role, content=content, anthropic_compatible=anthropic_compatible):
        return content, False

    if isinstance(content, list):
        annotated: list[Any] = []
        applied = False
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                updated = dict(item)
                if not isinstance(updated.get("cache_control"), dict):
                    updated["cache_control"] = dict(_CACHE_CONTROL)
                annotated.append(updated)
                applied = True
            else:
                annotated.append(item)
        if applied:
            return annotated, True

    return [{"type": "text", "text": message_content_to_text(content), "cache_control": dict(_CACHE_CONTROL)}], True


def annotate_openai_messages_for_prompt_cache(
    *,
    messages: list[dict[str, Any]],
    anthropic_compatible: bool,
) -> tuple[list[dict[str, Any]], PromptCacheMetadata]:
    annotated_messages: list[dict[str, Any]] = []
    applied_count = 0

    for message in messages:
        cloned = dict(message)
        annotated_content, applied = annotate_prompt_cache_content(
            role=cloned["role"],
            content=cloned.get("content"),
            anthropic_compatible=anthropic_compatible,
        )
        cloned["content"] = annotated_content
        if applied:
            applied_count += 1
        annotated_messages.append(cloned)

    return annotated_messages, {
        "prompt_cache_applied": bool(applied_count),
        "prompt_cache_message_count": applied_count,
        "provider_anthropic_compatible": bool(anthropic_compatible),
    }
