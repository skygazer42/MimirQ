
import re
from typing import Any

from app.rag.preprocessing.pii_anonymizer import find_pii_matches

_CN_PLATE_RE = re.compile(
    r"(?<![A-Z0-9])([京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][A-Z0-9]{5,6})(?![A-Z0-9])"
)
_CN_SOCIAL_SECURITY_LABELS = ("社会保障号", "社保号", "社保")

_KIND_MAP = {
    "email": "EMAIL_ADDRESS",
    "phone": "PHONE_NUMBER",
    "cn_id": "CN_ID",
    "credit_card": "CREDIT_CARD",
    "ip": "IP_ADDRESS",
}


def _append_unique(items: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    key = (entry["entity_type"], int(entry["start"]), int(entry["end"]))
    if any((it["entity_type"], int(it["start"]), int(it["end"])) == key for it in items):
        return
    items.append(entry)


def _append_detected_pii_entities(raw: str, entities: list[dict[str, Any]]) -> None:
    for match in find_pii_matches(raw, max_matches=100):
        entity_type = _KIND_MAP.get(match.kind)
        if not entity_type:
            continue
        _append_unique(
            entities,
            {
                "entity_type": entity_type,
                "start": int(match.start),
                "end": int(match.end),
                "text": str(match.text),
                "score": 0.9,
            },
        )


def _append_cn_plate_entities(raw: str, entities: list[dict[str, Any]]) -> None:
    for found in _CN_PLATE_RE.finditer(raw):
        _append_unique(
            entities,
            {
                "entity_type": "CN_LICENSE_PLATE",
                "start": int(found.start(1)),
                "end": int(found.end(1)),
                "text": str(found.group(1) or ""),
                "score": 0.88,
            },
        )


def _skip_whitespace(raw: str, cursor: int) -> int:
    while cursor < len(raw) and raw[cursor].isspace():
        cursor += 1
    return cursor


def _social_security_span_after_label(raw: str, *, label: str, label_start: int) -> tuple[int, int] | None:
    cursor = _skip_whitespace(raw, label_start + len(label))
    if cursor < len(raw) and raw[cursor] in {":", "："}:
        cursor += 1
    cursor = _skip_whitespace(raw, cursor)
    end = cursor
    while end < len(raw) and raw[end].isdigit() and end - cursor < 12:
        end += 1
    return (cursor, end) if 8 <= end - cursor <= 12 else None


def _append_cn_social_security_entities(raw: str, entities: list[dict[str, Any]]) -> None:
    for label in _CN_SOCIAL_SECURITY_LABELS:
        offset = 0
        while True:
            label_start = raw.find(label, offset)
            if label_start == -1:
                break
            span = _social_security_span_after_label(raw, label=label, label_start=label_start)
            if span is not None:
                cursor, end = span
                _append_unique(
                    entities,
                    {
                        "entity_type": "CN_SOCIAL_SECURITY",
                        "start": cursor,
                        "end": end,
                        "text": raw[cursor:end],
                        "score": 0.86,
                    },
                )
            offset = label_start + len(label)


def analyze_pii_text(text: str) -> dict[str, Any]:
    raw = str(text or "")
    entities: list[dict[str, Any]] = []

    _append_detected_pii_entities(raw, entities)
    _append_cn_plate_entities(raw, entities)
    _append_cn_social_security_entities(raw, entities)

    entities.sort(key=lambda item: (int(item["start"]), int(item["end"]), str(item["entity_type"])))
    return {
        "schema": "mimirq.pii_presidio_analysis.v1",
        "entities": entities,
    }


def anonymize_pii_text(text: str, *, mask: str = "[REDACTED]") -> dict[str, Any]:
    raw = str(text or "")
    analyzed = analyze_pii_text(raw)
    entities = list(analyzed.get("entities") or [])
    current = raw
    for entity in sorted(entities, key=lambda item: (int(item["start"]), int(item["end"])), reverse=True):
        start = int(entity["start"])
        end = int(entity["end"])
        current = current[:start] + str(mask) + current[end:]
    return {
        "schema": "mimirq.pii_presidio_anonymize.v1",
        "text": current,
        "changed": current != raw,
        "entities": entities,
    }


__all__ = ["analyze_pii_text", "anonymize_pii_text"]
