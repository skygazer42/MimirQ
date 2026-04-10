from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_kind(value: Any) -> str:
    return str(value or "").strip().lower()


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        if number != number:
            return None
        return float(number)
    except Exception:
        return None


def _field_aliases(field_name: str, spec: Mapping[str, Any] | None, prompt: str | None = None) -> list[str]:
    aliases: list[str] = []
    raw_aliases = (spec or {}).get("aliases")
    if isinstance(raw_aliases, list):
        aliases.extend(str(item).strip() for item in raw_aliases if str(item).strip())

    field_tokens = [part.strip() for part in re.split(r"[_\-\s]+", str(field_name or "")) if part.strip()]
    aliases.extend(field_tokens)

    if prompt:
        aliases.extend(token.strip() for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", str(prompt)) if token.strip())

    out: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        norm = _normalize_text(alias).lower()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _preferred_element_text(element: Mapping[str, Any]) -> str:
    attrs = element.get("attributes") if isinstance(element.get("attributes"), Mapping) else {}
    kind = _normalize_kind(element.get("kind"))
    if kind == "seal":
        primary = attrs.get("seal_primary") if isinstance(attrs.get("seal_primary"), Mapping) else {}
        for value in (attrs.get("seal_text"), primary.get("text"), element.get("text")):
            text = _normalize_text(value)
            if text:
                return text.removeprefix("印章识别：").strip()
        return ""
    return _normalize_text(element.get("text"))


def _match_element(
    *,
    element: Mapping[str, Any],
    source_kind: str | None,
    aliases: list[str],
) -> tuple[float, str]:
    kind = _normalize_kind(element.get("kind"))
    if source_kind and kind != source_kind:
        return 0.0, ""

    value = _preferred_element_text(element)
    if not value:
        return 0.0, ""

    confidence = _coerce_float(element.get("confidence")) or 0.0
    score = min(max(confidence, 0.0), 1.0) * 0.45
    if source_kind and kind == source_kind:
        score += 0.4

    value_norm = value.lower()
    if aliases:
        hit_count = sum(1 for alias in aliases if alias and alias in value_norm)
        score += min(0.15, hit_count * 0.05)

    return score, value


def _build_evidence(element: Mapping[str, Any], *, score: float, value: str) -> dict[str, Any]:
    bbox = element.get("bbox") if isinstance(element.get("bbox"), Mapping) else None
    return {
        "element_id": str(element.get("id") or "").strip() or None,
        "kind": _normalize_kind(element.get("kind")) or None,
        "page": int(element.get("page")) if isinstance(element.get("page"), int) else None,
        "bbox": dict(bbox) if isinstance(bbox, Mapping) else None,
        "text": value or None,
        "score": round(float(score), 3),
    }


def _match_markdown_alias_value(markdown: str, *, aliases: list[str]) -> str | None:
    lines = [line.strip() for line in str(markdown or "").splitlines() if line.strip()]
    for line in lines:
        for alias in aliases:
            if not alias:
                continue
            for sep in (":", "："):
                prefix = f"{alias}{sep}"
                if line.lower().startswith(prefix.lower()):
                    value = line[len(prefix) :].strip()
                    if value:
                        return value
    return None


def _match_markdown_sentence(markdown: str, *, aliases: list[str]) -> str | None:
    text = str(markdown or "").strip()
    if not text:
        return None
    sentences = [seg.strip() for seg in re.split(r"[。！？!?]\s*|\n+", text) if seg.strip()]
    for sentence in sentences:
        sentence_norm = sentence.lower()
        if any(alias in sentence_norm for alias in aliases if alias):
            return sentence
    return None


def _extract_field(
    *,
    field_name: str,
    spec: Mapping[str, Any] | None,
    markdown: str,
    elements: list[dict[str, Any]],
    prompt: str | None = None,
    max_evidence: int = 1,
) -> dict[str, Any]:
    source_kind = _normalize_kind((spec or {}).get("source_kind")) or None
    aliases = _field_aliases(field_name, spec, prompt)

    ranked: list[tuple[float, dict[str, Any], str]] = []
    for raw in elements or []:
        if not isinstance(raw, Mapping):
            continue
        score, value = _match_element(element=raw, source_kind=source_kind, aliases=aliases)
        if score <= 0.0 or not value:
            continue
        ranked.append((score, dict(raw), value))

    ranked.sort(key=lambda item: (float(item[0]), float(_coerce_float(item[1].get("confidence")) or 0.0)), reverse=True)
    if ranked:
        best_score, best_element, best_value = ranked[0]
        evidence = [
            _build_evidence(item, score=score, value=value)
            for score, item, value in ranked[: max(1, int(max_evidence or 1))]
        ]
        return {
            "value": best_value,
            "confidence": round(float(_coerce_float(best_element.get("confidence")) or best_score), 3),
            "evidence": evidence,
            "strategy": "element_match",
        }

    alias_value = _match_markdown_alias_value(markdown, aliases=aliases)
    if alias_value:
        return {
            "value": alias_value,
            "confidence": 0.25,
            "evidence": [],
            "strategy": "markdown_alias_match",
        }

    sentence_value = _match_markdown_sentence(markdown, aliases=aliases)
    if sentence_value:
        return {
            "value": sentence_value,
            "confidence": 0.18,
            "evidence": [],
            "strategy": "markdown_sentence_match",
        }

    fallback = _normalize_text(markdown).split(" ")
    fallback_value = " ".join(fallback[:20]).strip()
    return {
        "value": fallback_value or None,
        "confidence": 0.0 if not fallback_value else 0.1,
        "evidence": [],
        "strategy": "markdown_fallback" if fallback_value else "no_match",
    }


def extract_parsing_fields(
    *,
    markdown: str,
    elements: list[dict[str, Any]] | None,
    mode: str,
    schema: Mapping[str, Mapping[str, Any]] | None = None,
    prompt: str | None = None,
    field_hints: Mapping[str, Mapping[str, Any]] | None = None,
    max_evidence: int = 1,
) -> dict[str, dict[str, Any]]:
    mode_norm = str(mode or "schema").strip().lower() or "schema"
    field_specs = dict(schema or {}) if mode_norm == "schema" else dict(field_hints or {})
    if mode_norm == "prompt" and not field_specs:
        field_specs = {"prompt_result": {"type": "string", "aliases": _field_aliases("prompt_result", None, prompt)}}

    results: dict[str, dict[str, Any]] = {}
    for field_name, raw_spec in field_specs.items():
        spec = dict(raw_spec or {}) if isinstance(raw_spec, Mapping) else {}
        results[str(field_name)] = _extract_field(
            field_name=str(field_name),
            spec=spec,
            markdown=markdown,
            elements=list(elements or []),
            prompt=prompt,
            max_evidence=max_evidence,
        )
    return results


__all__ = ["extract_parsing_fields"]
