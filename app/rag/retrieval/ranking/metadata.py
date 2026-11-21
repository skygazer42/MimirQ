"""Rank constructed metadata anchors shared by candidate and document ordering."""

import re
import unicodedata
from collections.abc import Callable
from typing import Any, TypedDict

_SPACE_RE = re.compile(r"\s+")
_COMPACT_ANCHOR_DROP_RE = re.compile(r"[\s\"'“”‘’`´＂＇《》〈〉【】\[\]（）(){}]+")


def normalize_exact_anchor(value: str, *, compact: bool = False) -> str:
    text = value.strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _SPACE_RE.sub(" ", text.casefold()).strip()
    return _COMPACT_ANCHOR_DROP_RE.sub("", text) if compact else text


class MetadataAnchor(TypedDict):
    field: str
    value: str
    score: float
    norm: str


def rank_metadata_anchor_matches(matches: list[MetadataAnchor]) -> dict[str, Any]:
    if not matches:
        return {}

    # Keep the longest alias per field before combining independent anchors.
    filtered: list[MetadataAnchor] = []
    seen_norms: set[str] = set()
    for item in sorted(matches, key=lambda x: (-len(x["norm"]), -x["score"])):
        field = item["field"]
        norm = item["norm"]
        if any(kept["field"] == field and norm in kept["norm"] for kept in filtered):
            continue
        if norm in seen_norms:
            continue
        seen_norms.add(norm)
        filtered.append(item)

    ranked = sorted(
        filtered,
        key=lambda x: (-x["score"], -len(x["norm"]), x["field"]),
    )
    primary = ranked[0]
    aggregate = primary["score"]
    aggregate += 0.5 * sum(item["score"] for item in ranked[1:])
    aggregate = min(1.0, aggregate)

    fields = list(dict.fromkeys(item["field"] for item in ranked if item["field"]))
    values = [item["value"] for item in ranked if item["value"]]
    return {
        "field": primary["field"],
        "value": primary["value"],
        "score": round(aggregate, 6),
        "primary_score": round(primary["score"], 6),
        "fields": fields[:8],
        "values": values[:8],
    }


_METADATA_EXACT_ANCHOR_SKIP_FIELD_PARTS = (
    "id",
    "uuid",
    "hash",
    "path",
    "file",
    "url",
    "pipeline",
    "strategy",
    "plugin",
    "index",
    "keyword",
    "keywords",
)
_METADATA_EXACT_ANCHOR_SKIP_FIELD_PREFIXES = (
    "metadata_exact_match",
    "exact_phrase",
    "rerank",
)
_HEXISH_VALUE_RE = re.compile(r"^[a-f0-9]{12,}$", flags=re.IGNORECASE)
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_FIELD_PART_RE = re.compile(r"[^a-z0-9]+")


def looks_like_metadata_anchor(field: str, text: str, *, normalize: Callable[..., str]) -> bool:
    field_norm = field.strip().lower()
    if any(field_norm.startswith(prefix) for prefix in _METADATA_EXACT_ANCHOR_SKIP_FIELD_PREFIXES):
        return False
    field_parts = {p for p in _FIELD_PART_RE.split(field_norm) if p}
    if field_parts.intersection(_METADATA_EXACT_ANCHOR_SKIP_FIELD_PARTS):
        return False
    if field_norm.endswith(("_id", "_ids", "-id", ".id")):
        return False

    normalized = normalize(text)
    if len(normalized) < 4 or len(normalized) > 160:
        return False
    if "://" in normalized or "/" in normalized or "\\" in normalized:
        return False
    if _HEXISH_VALUE_RE.fullmatch(normalized.replace("-", "")):
        return False
    if normalized.isdigit():
        return False

    cjk_count = len(_CJK_CHAR_RE.findall(normalized))
    if cjk_count:
        return cjk_count >= 4
    if "_" in normalized and " " not in normalized:
        return False
    return len(normalized) >= 8


def match_metadata_anchors(
    query_norm: str, values: list[tuple[str, str]], *, normalize: Callable[..., str]
) -> dict[str, Any]:
    matches: list[MetadataAnchor] = []
    for field, anchor_text in values:
        if not looks_like_metadata_anchor(field, anchor_text, normalize=normalize):
            continue
        anchor_norm = normalize(anchor_text, compact=True)
        if not anchor_norm or anchor_norm not in query_norm:
            continue
        score = min(1.0, max(0.45, float(len(anchor_norm)) / float(max(1, len(query_norm)))))
        matches.append(
            {
                "field": field,
                "value": anchor_text,
                "score": round(score, 6),
                "norm": anchor_norm,
            }
        )

    return rank_metadata_anchor_matches(matches)
