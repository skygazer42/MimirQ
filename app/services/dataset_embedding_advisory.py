"""Structured embedding advisories derived from dataset precheck evidence."""


from typing import Any

from app.core.config import settings
from app.rag.embedding.config import get_supported_model_ids

_SCHEMA = "mimirq.dataset_embedding_advisory.v1"
_GENERIC_OPENAI_MODELS = {
    "openai/text-embedding-3-small",
    "openai_compatible/text-embedding-3-small",
    "text-embedding-3-small",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _non_negative_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalized_model_id(*, provider: Any, model: Any) -> str:
    provider_text = _clean(provider).lower()
    model_text = _clean(model)
    if not model_text:
        return ""
    if "/" in model_text:
        return model_text.casefold()
    if provider_text:
        return f"{provider_text}/{model_text}".casefold()
    return model_text.casefold()


def _configured_language_models() -> dict[str, str]:
    supported = set(get_supported_model_ids())
    configured = {
        "zh": _clean(getattr(settings, "EMBEDDING_MODEL_ZH", "")),
        "mixed": _clean(getattr(settings, "EMBEDDING_MODEL_MIXED", "")),
    }
    return {key: value for key, value in configured.items() if value and value in supported}


def _recommended_model_ids(configured: dict[str, str]) -> list[str]:
    supported = get_supported_model_ids()
    ordered: list[str] = []
    for value in (configured.get("zh"), configured.get("mixed")):
        if value and value not in ordered:
            ordered.append(value)
    for model_id in supported:
        lowered = model_id.casefold()
        if ("bge-m3" in lowered or "qwen3-embedding" in lowered) and model_id not in ordered:
            ordered.append(model_id)
    return ordered[:8]


def build_embedding_language_advisories(
    *,
    language_mix: dict[str, Any] | None,
    dataset_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Warn before first indexing when Chinese content still uses the generic default.

    The advisory is intentionally non-mutating: changing an embedding model in place
    would invalidate vectors already stored for an existing dataset. Operators can
    explicitly pin ``embedding_defaults`` for a new dataset or use the existing
    blue/green migration path for an indexed dataset.
    """

    counts = dict(language_mix or {})
    language_counts = {
        "zh": _non_negative_count(counts.get("zh")),
        "mixed": _non_negative_count(counts.get("mixed")),
        "en": _non_negative_count(counts.get("en")),
        "unknown": _non_negative_count(counts.get("unknown")),
    }
    if language_counts["zh"] + language_counts["mixed"] <= 0:
        return []

    metadata = dict(dataset_metadata or {})
    raw_defaults = metadata.get("embedding_defaults")
    defaults = dict(raw_defaults) if isinstance(raw_defaults, dict) else {}
    source = "dataset" if defaults else "global"
    provider = _clean(defaults.get("provider")) or _clean(getattr(settings, "EMBEDDING_PROVIDER", ""))
    model = _clean(defaults.get("model")) or _clean(getattr(settings, "EMBEDDING_MODEL", ""))
    model_id = _normalized_model_id(provider=provider, model=model)

    configured = _configured_language_models()
    routing_enabled = bool(getattr(settings, "EMBEDDING_LANGUAGE_ROUTING_ENABLED", False))
    routed_for_observed_language = routing_enabled and bool(
        (language_counts["zh"] and configured.get("zh"))
        or (language_counts["mixed"] and configured.get("mixed"))
    )
    if routed_for_observed_language or model_id not in _GENERIC_OPENAI_MODELS:
        return []

    return [
        {
            "schema": _SCHEMA,
            "code": "zh_or_mixed_corpus_uses_generic_embedding",
            "severity": "warning",
            "reason": "zh_or_mixed_detected_with_text_embedding_3_small",
            "language_mix": language_counts,
            "effective_embedding": {
                "source": source,
                "provider": provider,
                "model": model,
            },
            "recommended_action": "pin_dataset_embedding_defaults_before_first_index",
            "migration_action_for_indexed_dataset": "use_embedding_blue_green_migration",
            "configured_language_models": configured,
            "recommended_model_ids": _recommended_model_ids(configured),
            "mutates_existing_dataset": False,
        }
    ]


__all__ = ["build_embedding_language_advisories"]
