
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.services.dataset_profile_service import extract_language_bucket, quality_bucket_from_governance_quality


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _as_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except Exception:
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return {}
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return []


def _norm_bucket(value: Any, *, fallback: str = "unknown") -> str:
    s = str(value or "").strip().lower()
    return s or fallback


def _norm_hit_type(value: Any) -> str:
    s = _norm_bucket(value, fallback="unknown")
    # Keep this low-cardinality. Align with Citation.hit_type (vector/keyword/hybrid/mmr/tag)
    # and allow multi-modal expansions without breaking older data.
    return s if s in {"vector", "keyword", "hybrid", "mmr", "tag", "image", "table"} else "unknown"


def _percentile(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    if pct <= 0:
        return float(min(values))
    if pct >= 100:
        return float(max(values))
    vals = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not vals:
        return None
    # Nearest-rank percentile (1-indexed).
    k = int(math.ceil((pct / 100.0) * len(vals))) - 1
    k = max(0, min(k, len(vals) - 1))
    return float(vals[k])


def _mean(values: Sequence[float]) -> float | None:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not vals:
        return None
    return float(sum(vals) / len(vals))


def _get_attr(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def compute_suite_throughput(
    items: Sequence[Any],
    *,
    now: datetime | None = None,
    window_days: int = 7,
) -> dict[str, Any]:
    """
    Compute lightweight throughput + lead time stats for a suite.

    Returns JSON-friendly dict (seconds for durations).
    """
    now_ = now or _now_utc()
    window = timedelta(days=max(1, int(window_days or 0)))
    cutoff = now_ - window

    created_7d = 0
    reviewed_7d = 0
    approved_7d = 0

    draft_to_reviewed: list[float] = []
    reviewed_to_approved: list[float] = []
    draft_to_approved: list[float] = []

    for it in items or []:
        created_at = _get_attr(it, "created_at")
        reviewed_at = _get_attr(it, "reviewed_at")
        approved_at = _get_attr(it, "approved_at")

        if isinstance(created_at, datetime) and created_at >= cutoff:
            created_7d += 1
        if isinstance(reviewed_at, datetime) and reviewed_at >= cutoff:
            reviewed_7d += 1
        if isinstance(approved_at, datetime) and approved_at >= cutoff:
            approved_7d += 1

        if isinstance(created_at, datetime) and isinstance(reviewed_at, datetime) and reviewed_at >= created_at:
            draft_to_reviewed.append(float((reviewed_at - created_at).total_seconds()))
        if isinstance(reviewed_at, datetime) and isinstance(approved_at, datetime) and approved_at >= reviewed_at:
            reviewed_to_approved.append(float((approved_at - reviewed_at).total_seconds()))
        if isinstance(created_at, datetime) and isinstance(approved_at, datetime) and approved_at >= created_at:
            draft_to_approved.append(float((approved_at - created_at).total_seconds()))

    return {
        "window_days": int(window_days),
        "last_window": {
            "created": int(created_7d),
            "reviewed": int(reviewed_7d),
            "approved": int(approved_7d),
        },
        "draft_to_reviewed": {
            "count": int(len(draft_to_reviewed)),
            "p50_sec": _percentile(draft_to_reviewed, 50.0),
            "p90_sec": _percentile(draft_to_reviewed, 90.0),
            "mean_sec": _mean(draft_to_reviewed),
        },
        "reviewed_to_approved": {
            "count": int(len(reviewed_to_approved)),
            "p50_sec": _percentile(reviewed_to_approved, 50.0),
            "p90_sec": _percentile(reviewed_to_approved, 90.0),
            "mean_sec": _mean(reviewed_to_approved),
        },
        "draft_to_approved": {
            "count": int(len(draft_to_approved)),
            "p50_sec": _percentile(draft_to_approved, 50.0),
            "p90_sec": _percentile(draft_to_approved, 90.0),
            "mean_sec": _mean(draft_to_approved),
        },
    }


@dataclass(frozen=True, slots=True)
class CoverageBucket:
    key: str
    items: int
    references: int


@dataclass(frozen=True, slots=True)
class CoverageHeatmap:
    x: list[str]
    y: list[str]
    z: list[list[int]]
    metric: str


def _top_n_buckets(
    buckets: dict[str, tuple[set[str], int]],
    *,
    top_n: int,
) -> list[CoverageBucket]:
    """
    buckets: {bucket_key: (item_ids, ref_count)}
    """
    items = [
        (k, len(v[0]), int(v[1]))
        for k, v in (buckets or {}).items()
        if k is not None
    ]
    items.sort(key=lambda x: (-x[2], -x[1], str(x[0])))

    out: list[CoverageBucket] = []
    rest_items = 0
    rest_refs = 0
    cap = max(1, min(50, int(top_n or 0))) if top_n else 12
    for idx, (k, item_cnt, ref_cnt) in enumerate(items):
        if idx < cap:
            out.append(CoverageBucket(key=str(k), items=int(item_cnt), references=int(ref_cnt)))
        else:
            rest_items += int(item_cnt)
            rest_refs += int(ref_cnt)
    if rest_refs or rest_items:
        out.append(CoverageBucket(key="__other__", items=int(rest_items), references=int(rest_refs)))
    return out


def _build_hit_type_index(citations: list[Any]) -> dict[str, str]:
    hit_by_chunk: dict[str, str] = {}
    for citation in citations:
        citation_dict = _as_dict(citation)
        chunk_id = str(citation_dict.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        hit_by_chunk[chunk_id] = _norm_hit_type(citation_dict.get("hit_type"))
    return hit_by_chunk


def _coverage_dimensions(
    *,
    documents: dict[UUID, dict[str, Any]],
    document_id: UUID,
    chunk_id: str,
    hit_by_chunk: dict[str, str],
) -> tuple[str, str, str, str]:
    document = documents.get(document_id) or {}
    file_type = _norm_bucket(document.get("file_type") or "unknown")
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    language = _norm_bucket(extract_language_bucket(metadata) or "unknown")
    quality_bucket = _norm_bucket(quality_bucket_from_governance_quality(metadata.get("governance_quality")) or "unknown")
    channel = hit_by_chunk.get(chunk_id) or "unknown"
    return file_type, language, quality_bucket, channel


def _update_coverage_buckets(
    *,
    buckets: dict[str, dict[str, tuple[set[str], int]]],
    item_id: str,
    file_type: str,
    language: str,
    quality_bucket: str,
    channel: str,
) -> None:
    for dim, bucket_key in (
        ("file_type", file_type),
        ("language", language),
        ("quality_bucket", quality_bucket),
        ("channel", channel),
    ):
        current = buckets[dim].get(bucket_key)
        if current is None:
            current = (set(), 0)
        item_ids, ref_count = current
        item_ids.add(item_id)
        buckets[dim][bucket_key] = (item_ids, int(ref_count) + 1)


def _update_heatmap_state(
    *,
    cell_items: dict[tuple[str, str], set[str]],
    lang_refs: dict[str, int],
    ft_refs: dict[str, int],
    item_id: str,
    language: str,
    file_type: str,
) -> None:
    cell_key = (language, file_type)
    cell_items.setdefault(cell_key, set()).add(item_id)
    lang_refs[language] = int(lang_refs.get(language, 0)) + 1
    ft_refs[file_type] = int(ft_refs.get(file_type, 0)) + 1


def compute_suite_coverage(
    items: Sequence[Any],
    *,
    documents: dict[UUID, dict[str, Any]],
    top_n: int = 12,
    heatmap_top_n: int = 8,
) -> dict[str, Any]:
    """
    Compute coverage slices for EvidenceSuite items using their reference_sources.

    Coverage is computed over reference pointers with item-level uniqueness tracked:
    - `references`: count of reference pointers in the bucket
    - `items`: unique EvidenceItem ids that contribute references to the bucket
    """
    # dim -> bucket -> (item_id_set, ref_count)
    buckets: dict[str, dict[str, tuple[set[str], int]]] = {
        "language": {},
        "file_type": {},
        "quality_bucket": {},
        "channel": {},
    }

    # For heatmap: (language, file_type) -> item_id set
    cell_items: dict[tuple[str, str], set[str]] = {}
    lang_refs: dict[str, int] = {}
    ft_refs: dict[str, int] = {}

    for it in items or []:
        it_id_raw = _get_attr(it, "id")
        it_id = str(it_id_raw) if it_id_raw is not None else ""
        if not it_id:
            continue

        refs = _as_list(_get_attr(it, "reference_sources"))
        if not refs:
            continue

        snap = _as_dict(_get_attr(it, "retrieval_snapshot"))
        hit_by_chunk = _build_hit_type_index(_as_list(snap.get("citations")))

        for ref in refs:
            ref_dict = _as_dict(ref)
            document_id = _as_uuid(ref_dict.get("document_id"))
            chunk_id = str(ref_dict.get("chunk_id") or "").strip()
            if document_id is None:
                continue

            file_type, language, quality_bucket, channel = _coverage_dimensions(
                documents=documents,
                document_id=document_id,
                chunk_id=chunk_id,
                hit_by_chunk=hit_by_chunk,
            )
            _update_coverage_buckets(
                buckets=buckets,
                item_id=it_id,
                file_type=file_type,
                language=language,
                quality_bucket=quality_bucket,
                channel=channel,
            )
            _update_heatmap_state(
                cell_items=cell_items,
                lang_refs=lang_refs,
                ft_refs=ft_refs,
                item_id=it_id,
                language=language,
                file_type=file_type,
            )

    out: dict[str, Any] = {
        "language": [{"key": b.key, "items": b.items, "references": b.references} for b in _top_n_buckets(buckets["language"], top_n=top_n)],
        "file_type": [{"key": b.key, "items": b.items, "references": b.references} for b in _top_n_buckets(buckets["file_type"], top_n=top_n)],
        "quality_bucket": [
            {"key": b.key, "items": b.items, "references": b.references} for b in _top_n_buckets(buckets["quality_bucket"], top_n=top_n)
        ],
        "channel": [{"key": b.key, "items": b.items, "references": b.references} for b in _top_n_buckets(buckets["channel"], top_n=top_n)],
    }

    # Heatmap: pick top-N langs and file types by ref volume to keep payload bounded.
    h_n = max(2, min(20, int(heatmap_top_n or 0))) if heatmap_top_n else 8
    langs = sorted(lang_refs.items(), key=lambda x: (-int(x[1]), str(x[0])))[:h_n]
    fts = sorted(ft_refs.items(), key=lambda x: (-int(x[1]), str(x[0])))[:h_n]
    y = [k for k, _v in langs] or []
    x = [k for k, _v in fts] or []
    z: list[list[int]] = []
    for ly in y:
        row: list[int] = []
        for fx in x:
            row.append(int(len(cell_items.get((ly, fx), set()))))
        z.append(row)

    out["heatmaps"] = {
        "language_x_file_type": {"x": x, "y": y, "z": z, "metric": "items"}
    }
    return out


__all__ = ["compute_suite_coverage", "compute_suite_throughput"]
