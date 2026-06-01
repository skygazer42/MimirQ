"""
Hardcase discovery helpers (PII-safe).

Primary use-case (Wave26-T39):
- Cluster/dedupe negative MessageFeedback by `question_hash` from `rag_trace` metrics records.
- Keep outputs PII-safe by construction: never emit raw query text here.
- Deterministic + bounded: stable ordering and explicit caps.

This module is intentionally dependency-light so it can be used from API handlers,
scripts, and unit tests without pulling in heavy service graphs.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger

logger = get_logger(__name__)


def _safe_str(value: Any, *, max_len: int = 200) -> str | None:
    s = str(value or "").strip()
    if not s:
        return None
    lim = max(0, int(max_len or 0))
    if lim <= 0:
        return s
    return s[:lim]


def _to_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except Exception:
        return default


def _coerce_nonneg_int(value: Any, *, default: int = 0) -> int:
    iv = _to_int(value, default=default)
    return iv if iv >= 0 else default


def _extract_error_kind_counts(errors: Any) -> dict[str, int]:
    """
    Normalize retrieval errors into low-cardinality kind buckets.

    Expected input (metrics JSONL): ["timeout: ...", "rate_limited: ...", ...]
    Output: {"timeout": 3, "rate_limited": 1}
    """
    if not isinstance(errors, list) or not errors:
        return {}
    out: dict[str, int] = defaultdict(int)
    for e in errors:
        if not isinstance(e, str):
            continue
        kind = e.split(":", 1)[0].strip().lower()
        if not kind:
            continue
        out[kind[:30]] += 1
    return dict(out)


def _safe_rag_config_template(raw: Any) -> dict[str, Any] | None:
    """
    Keep only PII-safe, low-cardinality lineage fields for config template selection.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, Any] = {}

    key = _safe_str(raw.get("template_key"), max_len=64)
    if key:
        out["template_key"] = key

    if raw.get("version") is not None:
        try:
            out["version"] = int(raw.get("version"))
        except Exception as exc:
            logger.debug("Ignoring malformed hardcase rag config template version: %s", exc)

    ph = _safe_str(raw.get("patch_hash"), max_len=128)
    if ph:
        out["patch_hash"] = ph

    return out or None


def read_jsonl_tail(path: str | Path, *, max_bytes: int) -> tuple[list[dict[str, Any]], bool]:
    """
    Read the tail of a JSONL file (bounded) and parse dict records.

    Return: (records, truncated)
    `truncated=true` means we started reading from the middle of the file.
    """
    max_bytes = max(1, int(max_bytes or 0))
    p = Path(path)

    try:
        st = p.stat()
        size = int(st.st_size)
    except Exception:
        return [], False

    start = max(0, size - max_bytes)
    truncated = start > 0

    try:
        with p.open("rb") as f:
            if start:
                f.seek(start)
            raw = f.read()
    except Exception:
        return [], truncated

    if start:
        # Drop partial first line when reading from the middle.
        nl = raw.find(b"\n")
        if nl >= 0:
            raw = raw[nl + 1 :]

    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return [], truncated

    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = (line or "").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records, truncated


def build_rag_trace_index_from_records(
    *,
    records: Sequence[Mapping[str, Any]],
    tenant_id: str,
    cutoff_ms: int,
) -> dict[str, dict[str, Any]]:
    """
    Build a small lookup:
      { request_id: { request_id, ts_ms, question_hash, retrieval_config_hash, citations_count, ... } }

    Rules:
    - Filter to tenant_id + event=="rag_trace"
    - Filter to ts_ms >= cutoff_ms (best-effort)
    - Prefer latest record per request_id by ts_ms
    - PII-safe: do not carry question/query text
    """
    tenant_key = str(tenant_id or "").strip()
    cutoff = _to_int(cutoff_ms, default=0)

    best_by_request: dict[str, dict[str, Any]] = {}
    best_ts_by_request: dict[str, int] = {}

    for r in records or []:
        if not isinstance(r, Mapping):
            continue
        if str(r.get("event") or "") != "rag_trace":
            continue
        if tenant_key and str(r.get("tenant_id") or "") != tenant_key:
            continue

        ts_ms = _to_int(r.get("ts_ms"), default=0)
        if ts_ms and ts_ms < cutoff:
            continue

        request_id = _safe_str(r.get("request_id"), max_len=200)
        if not request_id:
            continue

        prev_ts = best_ts_by_request.get(request_id)
        # Prefer latest. For equal timestamps keep existing (stable, deterministic).
        if prev_ts is not None and ts_ms <= prev_ts:
            continue

        retrieval = r.get("retrieval") if isinstance(r.get("retrieval"), Mapping) else {}
        question_hash = _safe_str(r.get("question_hash") or r.get("query_hash"), max_len=64)
        retrieval_config_hash = _safe_str(
            (retrieval.get("retrieval_config_hash") if isinstance(retrieval, Mapping) else None) or r.get("retrieval_config_hash"),
            max_len=128,
        )

        citations_count: int
        if r.get("citations_count") is not None:
            citations_count = _coerce_nonneg_int(r.get("citations_count"), default=0)
        else:
            citations = r.get("citations") or []
            citations_count = int(len(citations)) if isinstance(citations, list) else 0

        errors = retrieval.get("errors") if isinstance(retrieval, Mapping) else None
        retrieval_error_kinds = _extract_error_kind_counts(errors)

        item: dict[str, Any] = {
            "request_id": request_id,
            "ts_ms": ts_ms,
            "question_hash": question_hash,
            "retrieval_config_hash": retrieval_config_hash,
            "citations_count": citations_count,
            "retrieval_error_kinds": retrieval_error_kinds,
        }

        rag_cfg_tmpl = _safe_rag_config_template(r.get("rag_config_template"))
        if rag_cfg_tmpl:
            item["rag_config_template"] = rag_cfg_tmpl

        best_by_request[request_id] = item
        best_ts_by_request[request_id] = ts_ms

    return best_by_request


def _merge_counts(dst: MutableMapping[str, int], src: Any) -> None:
    if not isinstance(src, Mapping):
        return
    for k, v in src.items():
        kk = _safe_str(k, max_len=30)
        if not kk:
            continue
        try:
            iv = int(v) if v is not None else 0
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if iv <= 0:
            continue
        dst[kk] = int(dst.get(kk, 0) or 0) + iv


def plan_feedback_hardcase_candidates(
    *,
    feedback_rows: Sequence[Mapping[str, Any]],
    trace_index: Mapping[str, Mapping[str, Any]],
    existing_feedback_ids: set[str],
    existing_question_hashes: set[str],
    max_candidates: int,
    include_existing: bool,
) -> list[dict[str, Any]]:
    """
    Join feedback to trace summaries and plan PII-safe hardcase candidates.

    Output schema is intentionally JSON-friendly and stable.
    """
    cap = max(0, min(int(max_candidates or 0), 200))
    if cap <= 0:
        return []

    existing_fids = {str(x) for x in (existing_feedback_ids or set()) if str(x)}
    existing_qh = {str(x) for x in (existing_question_hashes or set()) if str(x)}

    clusters: dict[str, dict[str, Any]] = {}

    for fb in feedback_rows or []:
        if not isinstance(fb, Mapping):
            continue

        feedback_id = _safe_str(fb.get("feedback_id") or fb.get("id"), max_len=200)
        if not feedback_id or feedback_id in existing_fids:
            continue

        request_id = _safe_str(fb.get("request_id"), max_len=200)
        if not request_id:
            continue

        trace = trace_index.get(request_id)
        if not isinstance(trace, Mapping):
            continue

        qh = _safe_str(trace.get("question_hash") or trace.get("query_hash"), max_len=64)
        if not qh:
            continue

        cl = clusters.get(qh)
        if cl is None:
            cl = {
                "question_hash": qh,
                "in_suite": bool(qh in existing_qh),
                "cluster_size": 0,
                "feedback_ids": [],
                "request_ids": [],
                "retrieval_error_kinds": defaultdict(int),
                "representative_trace": dict(trace),
            }
            clusters[qh] = cl

        cl["cluster_size"] = int(cl.get("cluster_size") or 0) + 1

        # Keep small samples for reviewers (bounded).
        fb_ids: list[str] = cl.get("feedback_ids") or []
        if feedback_id not in fb_ids and len(fb_ids) < 50:
            fb_ids.append(feedback_id)
        cl["feedback_ids"] = fb_ids

        req_ids: list[str] = cl.get("request_ids") or []
        added_new_request = False
        if request_id not in req_ids and len(req_ids) < 50:
            req_ids.append(request_id)
            added_new_request = True
        cl["request_ids"] = req_ids

        # Aggregate error kinds per *unique trace* (request_id) to avoid double-counting
        # when multiple feedback rows reference the same request.
        if added_new_request:
            _merge_counts(cl["retrieval_error_kinds"], trace.get("retrieval_error_kinds"))

        # Representative trace: prefer latest ts_ms (deterministic tie-break by request_id).
        rep = cl.get("representative_trace") or {}
        rep_ts = _to_int(rep.get("ts_ms"), default=0) if isinstance(rep, Mapping) else 0
        trace_ts = _to_int(trace.get("ts_ms"), default=0)
        if trace_ts > rep_ts:
            cl["representative_trace"] = dict(trace)
        elif trace_ts == rep_ts:
            rep_rid = str(rep.get("request_id") or "")
            cur_rid = str(trace.get("request_id") or "")
            if cur_rid and (not rep_rid or cur_rid < rep_rid):
                cl["representative_trace"] = dict(trace)

    candidates: list[dict[str, Any]] = []
    for qh, cl in clusters.items():
        in_suite = bool(cl.get("in_suite") or False)
        if in_suite and not include_existing:
            continue

        rep = cl.get("representative_trace") or {}
        rep_map = rep if isinstance(rep, Mapping) else {}

        err_counts: dict[str, int]
        raw_err = cl.get("retrieval_error_kinds")
        if isinstance(raw_err, Mapping):
            err_counts = {str(k): int(v) for k, v in raw_err.items() if k is not None}
        else:
            err_counts = {}

        item: dict[str, Any] = {
            "question_hash": qh,
            "cluster_size": int(cl.get("cluster_size") or 0),
            "in_suite": in_suite,
            "feedback_ids": list(cl.get("feedback_ids") or []),
            "request_ids": list(cl.get("request_ids") or []),
            "retrieval_config_hash": rep_map.get("retrieval_config_hash"),
            "citations_count": rep_map.get("citations_count"),
            "retrieval_error_kinds": err_counts,
        }

        if rep_map.get("rag_config_template") is not None:
            item["rag_config_template"] = rep_map.get("rag_config_template")

        candidates.append(item)

    # Deterministic ordering: larger clusters first, then hash.
    candidates.sort(key=lambda x: (-int(x.get("cluster_size") or 0), str(x.get("question_hash") or "")))
    return candidates[:cap]


def build_parse_risk_hardcase_candidate(
    *,
    query_hash: str,
    retrieval_mode: str,
    retrieval_profile: str | None,
    retrieval_config_hash: str | None,
    parse_risk: Mapping[str, Any] | None,
    ts_ms: int,
) -> dict[str, Any] | None:
    """
    Build a deterministic hardcase candidate from parse-risk signals.

    Returns None when parse risk is not actionable.
    """
    risk = parse_risk if isinstance(parse_risk, Mapping) else {}
    level = str(risk.get("level") or "").strip().lower()
    if level not in {"high", "medium"}:
        return None

    score: float
    try:
        score = float(risk.get("score") or 0.0)
    except Exception:
        score = 0.0
    reason_text = _safe_str(risk.get("reason"), max_len=120) or "parse_risk_tail"
    cfg_hash = _safe_str(retrieval_config_hash, max_len=128)

    dedupe_payload = {
        "reason": "parse_risk_tail",
        "query_hash": str(query_hash or "").strip(),
        "mode": str(retrieval_mode or "").strip(),
        "profile": str(retrieval_profile or "").strip() or None,
        "cfg_hash": cfg_hash,
        "parse_risk_level": level,
    }
    return {
        "schema": "mimirq.hardcase_candidate.v1",
        "reason": "parse_risk_tail",
        "query_hash": str(query_hash or "").strip(),
        "retrieval_mode": str(retrieval_mode or "").strip(),
        "retrieval_profile": (str(retrieval_profile or "").strip() or None),
        "retrieval_config_hash": cfg_hash,
        "parse_risk_level": level,
        "parse_risk_score": round(float(score), 3),
        "parse_risk_reason": reason_text,
        "dedupe_key": stable_hash(json.dumps(dedupe_payload, ensure_ascii=False, sort_keys=True), length=32),
        "ts_ms": int(max(0, ts_ms)),
    }


def evaluate_parse_risk_auto_enqueue_policy(
    *,
    parse_risk: Mapping[str, Any] | None,
    enabled: bool,
    allowed_levels: set[str] | list[str] | tuple[str, ...] | None,
    min_score: float,
) -> dict[str, Any]:
    risk = parse_risk if isinstance(parse_risk, Mapping) else {}
    level = str(risk.get("level") or "").strip().lower()
    score: float
    try:
        score = float(risk.get("score") or 0.0)
    except Exception:
        score = 0.0

    levels = {str(x).strip().lower() for x in (allowed_levels or []) if str(x).strip()}
    if not levels:
        levels = {"high", "medium"}

    enqueue = bool(enabled)
    reason = "disabled"
    if not enabled:
        enqueue = False
        reason = "disabled"
    elif not bool(risk.get("hardcase_eligible")):
        enqueue = False
        reason = "hardcase_not_eligible"
    elif level not in levels:
        enqueue = False
        reason = "level_filtered"
    elif float(score) < float(min_score):
        enqueue = False
        reason = "score_below_min"
    else:
        enqueue = True
        reason = "eligible"

    return {
        "enabled": bool(enabled),
        "enqueue": bool(enqueue),
        "reason": reason,
        "level": level or "unknown",
        "score": round(float(score), 3),
        "allowed_levels": sorted(levels),
        "min_score": round(float(min_score), 3),
    }


__all__ = [
    "build_rag_trace_index_from_records",
    "build_parse_risk_hardcase_candidate",
    "evaluate_parse_risk_auto_enqueue_policy",
    "plan_feedback_hardcase_candidates",
    "read_jsonl_tail",
]
