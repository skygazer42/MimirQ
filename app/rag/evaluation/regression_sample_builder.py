from __future__ import annotations

import math
import re
from typing import Any

from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.rag.core.text import is_claim_supported, split_into_claims
from app.rag.evaluation.chunk_diagnostics import compute_chunk_diagnostics
from app.rag.evaluation.multihop import score_multihop_citation_chain
from app.rag.pipeline_plugins.contracts import (
    DISPLAY_METADATA_KEY,
    EVALUABLE_METADATA_KEY,
    INDEXED_METADATA_KEY,
    RECORD_IDENTITY_METADATA_KEY,
)

logger = get_logger(__name__)

_EXPECTED_METADATA_PLATFORM_SCALAR_KEYS = {
    "pipeline_hash",
    "doc_pipeline_key",
    "chunk_strategy",
    "resolved_chunk_strategy",
    "chunk_python_plugin",
    "governance_python_plugin",
}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _coerce_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _dedup_ids(raw_items: Any, *, key: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items or []:
        d = _coerce_dict(item)
        raw = d.get(key)
        if not raw:
            continue
        cid = str(raw)
        if cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


_WS_RE = re.compile(r"\s+")
_QUOTED_SPAN_RE = re.compile(r"[\"“”]([^\"“”]{4,500})[\"“”]")


def _collapse_ws(text: Any) -> str:
    return _WS_RE.sub(" ", str(text or "").strip())


def _stable_ref_key(src: Any) -> str | None:
    d = _coerce_dict(src)
    dk = str(d.get("doc_pipeline_key") or "").strip()
    if not dk:
        return None
    idx_raw = d.get("chunk_index")
    try:
        idx = int(idx_raw) if idx_raw is not None else None
    except Exception:
        idx = None
    if idx is None or idx < 0:
        return None
    return f"{dk}:{idx}"


def _stable_citation_key(cit: Any) -> str | None:
    d = _coerce_dict(cit)
    dk = str(d.get("doc_pipeline_key") or "").strip()
    if not dk:
        return None
    idx_raw = d.get("chunk_index")
    try:
        idx = int(idx_raw) if idx_raw is not None else None
    except Exception:
        idx = None
    if idx is None or idx < 0:
        return None
    return f"{dk}:{idx}"


def _record_identity_key_from_mapping(value: Any) -> str | None:
    d = _coerce_dict(value)
    raw = d.get("_record_identity") or d.get("record_identity")
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or "").strip()
    if key:
        return key
    fields = raw.get("fields")
    if not isinstance(fields, dict) or not fields:
        return None
    parts: list[str] = []
    for name in sorted(str(k) for k in fields):
        field_value = fields.get(name)
        if not _value_present(field_value):
            continue
        parts.append(f"{name}={field_value}")
    return "|".join(parts) if parts else None


def _record_identity_key(obj: Any) -> str | None:
    root_key = _record_identity_key_from_mapping(obj)
    if root_key:
        return root_key
    for meta in _citation_metadata_bases(obj):
        meta_key = _record_identity_key_from_mapping(meta)
        if meta_key:
            return meta_key
    return None


def _family_key(obj: Any) -> str | None:
    """
    Best-effort hierarchy family key extractor.

    Notes:
    - Citations may carry `family_collapse_key`/`hierarchy_family_key` when hierarchy
      recall overlay is enabled.
    - Reference sources may optionally carry the same keys (added by newer pipelines
      or stored in regression bundles).
    """
    d = _coerce_dict(obj)
    for key in (
        "family_collapse_key",
        "hierarchy_family_key",
        "parent_id",
        "parent_node_id",
    ):
        raw = d.get(key)
        if raw is None:
            continue
        s = str(raw).strip()
        if s:
            return s
    return None


def _metadata_value(meta: dict[str, Any], key: str) -> Any:
    if "." not in key:
        return meta.get(key)
    cur: Any = meta
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _value_present(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _expected_metadata_from_case_extra(extra: Any) -> dict[str, Any]:
    extra_d = extra if isinstance(extra, dict) else {}
    raw = extra_d.get("expected_metadata")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        k = str(key or "").strip()
        if not k or not _value_present(value):
            continue
        out[k] = value
        if len(out) >= 60:
            break
    return out


def _answer_key_points_from_case_extra(extra: Any) -> list[str]:
    extra_d = extra if isinstance(extra, dict) else {}
    raw = extra_d.get("answer_key_points") or extra_d.get("expected_answer_key_points")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = _collapse_ws(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= 80:
            break
    return out


def _answer_key_point_aliases_from_case_extra(extra: Any) -> dict[str, list[str]]:
    extra_d = extra if isinstance(extra, dict) else {}
    raw = extra_d.get("answer_key_point_aliases")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, values in raw.items():
        point = _collapse_ws(key)
        if not point:
            continue
        raw_values = values if isinstance(values, list) else [values]
        aliases: list[str] = []
        seen: set[str] = set()
        for value in raw_values:
            alias = _collapse_ws(value)
            if not alias or alias in seen:
                continue
            seen.add(alias)
            aliases.append(alias)
            if len(aliases) >= 20:
                break
        if aliases:
            out[point] = aliases
    return out


def _citation_metadata_bases(citation: Any) -> list[dict[str, Any]]:
    root = _coerce_dict(citation)
    bases: list[dict[str, Any]] = []
    for candidate in (
        root,
        root.get("metadata"),
        root.get("doc_metadata"),
        root.get("chunk_metadata"),
    ):
        if isinstance(candidate, dict):
            bases.append(candidate)
    return bases


def _citation_metadata_containers(citation: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for base in _citation_metadata_bases(citation):
        for view_key in (EVALUABLE_METADATA_KEY, INDEXED_METADATA_KEY, DISPLAY_METADATA_KEY):
            view = base.get(view_key)
            if isinstance(view, dict) and id(view) not in seen:
                seen.add(id(view))
                out.append(view)
        record_identity = base.get(RECORD_IDENTITY_METADATA_KEY) or base.get("record_identity")
        if isinstance(record_identity, dict):
            fields = record_identity.get("fields")
            if isinstance(fields, dict) and id(fields) not in seen:
                seen.add(id(fields))
                out.append(fields)
        scalar = {
            key: base.get(key)
            for key in _EXPECTED_METADATA_PLATFORM_SCALAR_KEYS
            if key in base and _value_present(base.get(key))
        }
        if scalar:
            out.append(scalar)
    return out


def _values_match(expected: Any, actual: Any) -> bool:
    if not _value_present(actual):
        return False
    if isinstance(expected, dict) or isinstance(actual, dict):
        return expected == actual

    if isinstance(expected, (list, tuple, set)):
        expected_values = [str(v).strip() for v in expected if _value_present(v)]
        if not expected_values:
            return False
        if isinstance(actual, (list, tuple, set)):
            actual_values = {str(v).strip() for v in actual if _value_present(v)}
            return set(expected_values).issubset(actual_values)
        return str(actual).strip() in set(expected_values)

    if isinstance(actual, (list, tuple, set)):
        expected_value = str(expected).strip()
        return expected_value in {str(v).strip() for v in actual if _value_present(v)}

    return actual == expected or str(actual).strip() == str(expected).strip()


def _citation_matches_expected_metadata(citation: Any, expected_metadata: dict[str, Any]) -> bool:
    if not expected_metadata:
        return False
    for key, expected_value in expected_metadata.items():
        matched = False
        for meta in _citation_metadata_containers(citation):
            if _values_match(expected_value, _metadata_value(meta, key)):
                matched = True
                break
        if not matched:
            return False
    return True


def _expected_metadata_metrics(*, expected_metadata: dict[str, Any], citations: list[Any]) -> dict[str, Any]:
    if not expected_metadata:
        return {}

    matched_keys: set[str] = set()
    for key, expected_value in expected_metadata.items():
        for citation in citations or []:
            if any(
                _values_match(expected_value, _metadata_value(meta, key))
                for meta in _citation_metadata_containers(citation)
            ):
                matched_keys.add(key)
                break

    fields_total = int(len(expected_metadata))
    fields_matched = int(len(matched_keys))
    missing_keys = [key for key in expected_metadata if key not in matched_keys][:20]
    hit = any(_citation_matches_expected_metadata(citation, expected_metadata) for citation in (citations or []))
    return {
        "expected_metadata_hit": bool(hit),
        "expected_metadata_recall": round(float(fields_matched) / max(1, fields_total), 4),
        "expected_metadata_fields_total": fields_total,
        "expected_metadata_fields_matched": fields_matched,
        "expected_metadata_missing_keys": missing_keys,
    }


def build_expected_metadata_metrics_summary(items_meta: list[dict[str, Any]]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for meta in items_meta or []:
        if not isinstance(meta, dict):
            continue
        if meta.get("expected_metadata_hit") is None and meta.get("expected_metadata_recall") is None:
            continue
        cases.append(meta)
    if not cases:
        return {}

    hit_values = [
        1.0 if bool(meta.get("expected_metadata_hit")) else 0.0
        for meta in cases
        if meta.get("expected_metadata_hit") is not None
    ]
    recall_values: list[float] = []
    fields_total = 0
    fields_matched = 0
    for meta in cases:
        try:
            if meta.get("expected_metadata_recall") is not None:
                recall_values.append(float(meta.get("expected_metadata_recall")))
        except Exception as exc:
            logger.debug("Ignoring expected metadata recall coercion failure: %s", exc)
        try:
            fields_total += max(0, int(meta.get("expected_metadata_fields_total") or 0))
        except Exception as exc:
            logger.debug("Ignoring expected metadata field-total coercion failure: %s", exc)
        try:
            fields_matched += max(0, int(meta.get("expected_metadata_fields_matched") or 0))
        except Exception as exc:
            logger.debug("Ignoring expected metadata field-matched coercion failure: %s", exc)

    return {
        "expected_metadata_hit_rate": (round(sum(hit_values) / len(hit_values), 4) if hit_values else None),
        "expected_metadata_recall": (round(sum(recall_values) / len(recall_values), 4) if recall_values else None),
        "expected_metadata_cases_total": int(len(cases)),
        "expected_metadata_fields_total": int(fields_total),
        "expected_metadata_fields_matched": int(fields_matched),
    }


def _quote_signature(text: Any, *, max_chars: int = 120) -> str | None:
    """
    Produce a small, normalized quote signature used for best-effort matching
    when chunk ids change.
    """
    max_chars = max(20, int(max_chars or 0))
    norm = _collapse_ws(text).casefold()
    if len(norm) < 24:
        return None
    return norm[:max_chars]


def _citation_text_for_quote_match(cit: Any) -> str:
    d = _coerce_dict(cit)
    # Prefer citation snippet, fall back to retrieved_contexts later if needed.
    return _collapse_ws(d.get("chunk_content") or d.get("quote") or "").casefold()


def _answer_key_point_in_text(point: str, text: str, aliases: dict[str, list[str]]) -> bool:
    haystack = _collapse_ws(text).casefold()
    if not haystack:
        return False
    candidates = [point, *(aliases.get(point) or [])]
    for candidate in candidates:
        needle = _collapse_ws(candidate).casefold()
        if needle and needle in haystack:
            return True
    return False


def _deterministic_faithfulness(answer: str, contexts: list[Any], *, max_evidence_chars: int = 24_000) -> float | None:
    """
    Deterministic, bounded faithfulness proxy for offline regression gates.

    Approach:
    - split answer into atomic claims
    - count how many claims are supported by the joined evidence text
    - score = supported / total

    Notes:
    - Heuristic only; this is not a semantic verifier.
    - Uncertainty/refusal phrasing is treated as supported by `is_claim_supported`.
    """
    raw_answer = str(answer or "").strip()
    if not raw_answer:
        return None

    claims = split_into_claims(raw_answer, max_claims=24)
    if not claims:
        return None

    joined = "\n".join([str(c or "") for c in (contexts or []) if str(c or "").strip()])
    evidence = joined
    if max_evidence_chars and max_evidence_chars > 0 and len(evidence) > int(max_evidence_chars):
        evidence = evidence[: int(max_evidence_chars)]

    supported = 0
    total = 0
    for claim in claims:
        c = str(claim or "").strip()
        if not c:
            continue
        total += 1
        if is_claim_supported(c, evidence):
            supported += 1

    if total <= 0:
        return None
    return round(float(supported) / float(total), 4)


def _quote_verifiability(answer: str, contexts: list[Any], *, max_quotes: int = 24) -> float | None:
    quotes = [_collapse_ws(match.group(1)).casefold() for match in _QUOTED_SPAN_RE.finditer(str(answer or ""))]
    quotes = [quote for quote in quotes if len(quote) >= 4][: max(1, int(max_quotes or 1))]
    if not quotes:
        return None

    evidence = _collapse_ws("\n".join([str(c or "") for c in contexts or []])).casefold()
    if not evidence:
        return 0.0

    verified = sum(1 for quote in quotes if quote in evidence)
    return round(float(verified) / float(len(quotes)), 4)


def build_regression_sample(case: Any, item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Build kwargs for RAGAS SingleTurnSample plus per-item meta used for audit/gates.

    This is intentionally pure-ish (no DB access) so it can be unit-tested.
    """
    question = str(item.get("question") or item.get("user_input") or "")
    response = str(item.get("response") or "")
    retrieved_contexts = list(item.get("retrieved_contexts") or [])

    expected_answer = _get(case, "expected_answer", None)
    reference = str(expected_answer or "")

    reference_sources = _get(case, "reference_sources", None) or []
    reference_context_ids = _dedup_ids(reference_sources, key="chunk_id")
    reference_contexts: list[str] = []
    for src in reference_sources or []:
        d = _coerce_dict(src)
        quote = str(d.get("quote") or "").strip()
        if quote:
            reference_contexts.append(quote)

    citations = item.get("citations") or []
    extra = _get(case, "extra", None)
    extra_d = extra if isinstance(extra, dict) else {}
    expected_metadata = _expected_metadata_from_case_extra(extra_d)
    answer_key_points = _answer_key_points_from_case_extra(extra_d)
    answer_key_point_aliases = _answer_key_point_aliases_from_case_extra(extra_d)

    citation_eval_limit: int | None = None
    raw_citation_eval_limit = item.get("citation_eval_limit")
    if raw_citation_eval_limit is not None:
        try:
            parsed_limit = int(raw_citation_eval_limit)
        except (TypeError, ValueError):
            parsed_limit = 0
        if parsed_limit > 0:
            citation_eval_limit = parsed_limit

    citations_ranked_all: list[Any] = []
    seen_cids: set[str] = set()
    for c in citations or []:
        d = _coerce_dict(c)
        cid = str(d.get("chunk_id") or "").strip()
        if not cid:
            continue
        if cid in seen_cids:
            continue
        seen_cids.add(cid)
        citations_ranked_all.append(c)
    citations_ranked = (
        citations_ranked_all[:citation_eval_limit]
        if citation_eval_limit is not None
        else citations_ranked_all
    )
    retrieved_context_ids = _dedup_ids(citations_ranked, key="chunk_id")

    # Retrieval quality signals (non-LLM):
    # - recall: fraction of human-verified evidence sources that were matched by retrieval
    # - hit@k: whether any evidence source appears in the top-k retrieved list
    # Matching strategy (best-effort):
    # 1) chunk_id exact match (fast path)
    # 2) doc_pipeline_key + chunk_index match (version-stable)
    # 3) quote signature substring match (fallback when ids drift)
    ref_set = set(reference_context_ids or [])
    ret_list = retrieved_context_ids or []
    ret_set = set(ret_list)

    ref_keys: list[str] = []
    ref_record_keys: list[str] = []
    ref_quotes: list[str] = []
    for src in reference_sources or []:
        k = _stable_ref_key(src)
        if k:
            ref_keys.append(k)
        rk = _record_identity_key(src)
        if rk:
            ref_record_keys.append(rk)
        qsig = _quote_signature(_coerce_dict(src).get("quote"))
        if qsig:
            ref_quotes.append(qsig)
    ref_key_set = set(ref_keys)
    ref_record_key_set = set(ref_record_keys)

    cit_keys: list[str] = []
    cit_record_keys: list[str] = []
    cit_texts: list[str] = []
    for c in citations_ranked:
        ck = _stable_citation_key(c)
        if ck:
            cit_keys.append(ck)
        crk = _record_identity_key(c)
        if crk:
            cit_record_keys.append(crk)
        cit_texts.append(_citation_text_for_quote_match(c))
    cit_key_set = set(cit_keys)
    cit_record_key_set = set(cit_record_keys)
    cit_text_joined = "\n".join([t for t in cit_texts if t]) if cit_texts else ""

    def _citation_matches_any_ref(i: int) -> bool:
        if i < 0 or i >= len(citations_ranked):
            return False
        d = _coerce_dict(citations_ranked[i])
        cid = str(d.get("chunk_id") or "").strip()
        if cid and cid in ref_set:
            return True

        ck = _stable_citation_key(d)
        if ck and ck in ref_key_set:
            return True

        crk = _record_identity_key(d)
        if crk and crk in ref_record_key_set:
            return True

        if ref_quotes:
            text_i = _citation_text_for_quote_match(d)
            if text_i:
                for qsig in ref_quotes:
                    if qsig and qsig in text_i:
                        return True
        return False

    def _ref_source_matched(src: Any) -> bool:
        d = _coerce_dict(src)
        cid = str(d.get("chunk_id") or "").strip()
        if cid and cid in ret_set:
            return True
        k = _stable_ref_key(src)
        if k and k in cit_key_set:
            return True
        rk = _record_identity_key(src)
        if rk and rk in cit_record_key_set:
            return True
        qsig = _quote_signature(d.get("quote"))
        if qsig and cit_text_joined and qsig in cit_text_joined:
            return True
        return False

    retrieval_recall: float | None = None
    retrieval_hit: bool | None = None
    retrieval_mrr: float | None = None
    retrieval_ndcg_at_10: float | None = None
    retrieval_ndcg_at_20: float | None = None
    hit_at_1: bool | None = None
    hit_at_3: bool | None = None
    hit_at_5: bool | None = None
    hit_at_10: bool | None = None
    hit_at_20: bool | None = None
    retrieval_doc_recall: float | None = None
    retrieval_doc_hit: bool | None = None
    retrieval_family_recall: float | None = None
    retrieval_family_hit: bool | None = None
    relevance_flags: list[bool] = []
    ref_total: int | None = None
    matched_refs: int | None = None
    missed_ref_ids: list[str] = []
    if reference_sources:
        ref_total = len(list(reference_sources or []))
        matched_refs = sum(1 for src in (reference_sources or []) if _ref_source_matched(src))
        retrieval_recall = round(float(matched_refs) / max(1, int(ref_total)), 4)
        retrieval_hit = bool(matched_refs > 0)

        # Rank-based metrics consider a citation "relevant" if it matches any reference source.
        rank_first: int | None = None
        for i in range(len(citations_ranked)):
            rel = _citation_matches_any_ref(i)
            relevance_flags.append(rel)
            if rel and rank_first is None:
                rank_first = i + 1

        if rank_first is not None and rank_first > 0:
            retrieval_mrr = round(1.0 / float(rank_first), 4)
        else:
            retrieval_mrr = 0.0

        # NDCG@K: binary relevance. Ideal ordering assumes each reference source can be hit by one retrieved item.
        def _ndcg_at(k: int) -> float:
            kk = max(1, int(k or 0))
            dcg = 0.0
            for idx, rel in enumerate(relevance_flags[:kk], 1):
                if rel:
                    dcg += 1.0 / math.log2(idx + 1)

            idcg = 0.0
            ideal_relevant = max(int(ref_total or 0), sum(1 for rel in relevance_flags[:kk] if rel))
            for idx in range(1, min(kk, ideal_relevant) + 1):
                idcg += 1.0 / math.log2(idx + 1)
            return round(dcg / idcg, 4) if idcg > 0.0 else 0.0

        retrieval_ndcg_at_10 = _ndcg_at(10)
        retrieval_ndcg_at_20 = _ndcg_at(20)

        def _hit_at(k: int) -> bool:
            kk = max(0, int(k or 0))
            return any(relevance_flags[:kk]) if kk > 0 else False

        hit_at_1 = _hit_at(1)
        hit_at_3 = _hit_at(3)
        hit_at_5 = _hit_at(5)
        hit_at_10 = _hit_at(10)
        hit_at_20 = _hit_at(20)

        # Document-level recall: unique evidence document ids hit by retrieval.
        ref_doc_set = {str(_coerce_dict(s).get("document_id") or "").strip() for s in (reference_sources or [])}
        ref_doc_set = {d for d in ref_doc_set if d}
        cit_doc_set = {str(_coerce_dict(c).get("document_id") or "").strip() for c in citations_ranked}
        cit_doc_set = {d for d in cit_doc_set if d}
        if ref_doc_set:
            matched_docs = int(len(ref_doc_set & cit_doc_set))
            retrieval_doc_recall = round(float(matched_docs) / max(1, int(len(ref_doc_set))), 4)
            retrieval_doc_hit = bool(matched_docs > 0)

        # Family-level recall: unique evidence families hit by retrieval. This is only
        # computable when reference_sources carry family keys (optional).
        ref_fams = [_family_key(s) for s in (reference_sources or [])]
        ref_fam_set = {k for k in ref_fams if k}
        if ref_fam_set:
            cit_fams = [_family_key(c) for c in citations_ranked]
            cit_fam_set = {k for k in cit_fams if k}
            matched_fams = int(len(ref_fam_set & cit_fam_set))
            retrieval_family_recall = round(float(matched_fams) / max(1, int(len(ref_fam_set))), 4)
            retrieval_family_hit = bool(matched_fams > 0)

        # Missed reference sources (PII-minimal ids only, for explanations/debug).
        for src in (reference_sources or []):
            if _ref_source_matched(src):
                continue
            sk = _stable_ref_key(src)
            fallback = str(_coerce_dict(src).get("chunk_id") or "").strip()
            raw_id = sk or fallback
            if not raw_id:
                continue
            missed_ref_ids.append(stable_hash(raw_id, length=16))
            if len(missed_ref_ids) >= 6:
                break

    citation_accuracy: float | None = None
    if reference_sources and citations_ranked:
        citation_accuracy = round(float(sum(1 for rel in relevance_flags if rel)) / float(len(citations_ranked)), 4)
    citation_coverage = retrieval_recall

    retrieval_effective_context_rate: float | None = None
    retrieval_noise_rate: float | None = None
    retrieval_effective_records: int | None = None
    retrieval_evaluated_records: int | None = None
    if answer_key_points and citations_ranked:
        effective_flags: list[bool] = []
        for index, citation in enumerate(citations_ranked):
            text_parts = [_citation_text_for_quote_match(citation)]
            if index < len(retrieved_contexts):
                text_parts.append(_collapse_ws(retrieved_contexts[index]).casefold())
            text = "\n".join(part for part in text_parts if part)
            effective_flags.append(
                any(
                    _answer_key_point_in_text(point, text, answer_key_point_aliases)
                    for point in answer_key_points
                )
            )
        retrieval_evaluated_records = int(len(effective_flags))
        retrieval_effective_records = int(sum(1 for flag in effective_flags if flag))
        retrieval_effective_context_rate = round(
            float(retrieval_effective_records) / max(1, retrieval_evaluated_records),
            4,
        )
        retrieval_noise_rate = round(1.0 - retrieval_effective_context_rate, 4)

    top_rel = item.get("top_relevance_score")
    try:
        top_rel_f = float(top_rel) if top_rel is not None else None
    except Exception:
        top_rel_f = None

    expected_refusal = None
    for key in ("expected_refusal", "should_refuse", "expected_abstain"):
        if key in extra_d:
            expected_refusal = bool(extra_d.get(key))
            break

    faithfulness_det = _deterministic_faithfulness(response, retrieved_contexts)
    atomic_faithfulness = faithfulness_det
    hallucination_rate = round(1.0 - float(faithfulness_det), 4) if faithfulness_det is not None else None
    quote_verifiability = _quote_verifiability(response, retrieved_contexts)

    # Chunk-level diagnostics (P0): attribution/utilization/noise/self-knowledge.
    ref_evidence_parts: list[str] = []
    if reference.strip():
        ref_evidence_parts.append(reference.strip())
    ref_evidence_parts.extend([str(x or "").strip() for x in (reference_contexts or []) if str(x or "").strip()])
    reference_evidence_text = "\n".join(ref_evidence_parts).strip() or None

    context_relevance: list[bool] | None = None
    if reference_sources:
        context_relevance = []
        for i in range(len(retrieved_contexts or [])):
            context_relevance.append(bool(relevance_flags[i]) if i < len(relevance_flags) else False)

    chunk_diag = compute_chunk_diagnostics(
        answer=response,
        retrieved_contexts=[str(c or "") for c in (retrieved_contexts or [])],
        context_relevance=context_relevance,
        reference_evidence_text=reference_evidence_text,
    )

    reasoning_hops_raw = _get(case, "reasoning_hops", None)
    if not isinstance(reasoning_hops_raw, list):
        reasoning_hops_raw = extra_d.get("reasoning_hops")
    reasoning_hops = [
        str(x) for x in (reasoning_hops_raw or []) if str(x or "").strip()
    ][:20]

    evidence_chain_raw = _get(case, "evidence_chain", None)
    if not isinstance(evidence_chain_raw, list):
        evidence_chain_raw = extra_d.get("evidence_chain")
    evidence_chain: list[dict[str, Any]] = []
    for item_raw in (evidence_chain_raw or []):
        row = _coerce_dict(item_raw)
        if not row:
            continue
        evidence_chain.append(row)
        if len(evidence_chain) >= 20:
            break

    multihop = score_multihop_citation_chain(
        evidence_chain=evidence_chain,
        citations=[_coerce_dict(c) for c in citations_ranked],
        reasoning_hops=reasoning_hops,
        top_k=20,
    )

    meta = {
        "abstain_triggered": bool(item.get("abstain_triggered")) if "abstain_triggered" in item else None,
        "abstain_reason": item.get("abstain_reason"),
        "top_relevance_score": top_rel_f,
        "retrieval_recall": retrieval_recall,
        "retrieval_hit": retrieval_hit,
        "retrieval_mrr": retrieval_mrr,
        "retrieval_ndcg_at_10": retrieval_ndcg_at_10,
        "retrieval_ndcg_at_20": retrieval_ndcg_at_20,
        "retrieval_hit_at_1": hit_at_1,
        "retrieval_hit_at_3": hit_at_3,
        "retrieval_hit_at_5": hit_at_5,
        "retrieval_hit_at_10": hit_at_10,
        "retrieval_hit_at_20": hit_at_20,
        "retrieval_doc_recall": retrieval_doc_recall,
        "retrieval_doc_hit": retrieval_doc_hit,
        "retrieval_family_recall": retrieval_family_recall,
        "retrieval_family_hit": retrieval_family_hit,
        "citation_accuracy": citation_accuracy,
        "citation_coverage": citation_coverage,
        "retrieval_effective_context_rate": retrieval_effective_context_rate,
        "retrieval_noise_rate": retrieval_noise_rate,
        "retrieval_effective_records": retrieval_effective_records,
        "retrieval_evaluated_records": retrieval_evaluated_records,
        "quote_verifiability": quote_verifiability,
        "atomic_faithfulness": atomic_faithfulness,
        "hallucination_rate": hallucination_rate,
        "faithfulness_det": faithfulness_det,
        "chunk_utilization": chunk_diag.get("chunk_utilization"),
        "chunk_attribution": chunk_diag.get("chunk_attribution"),
        "noise_sensitivity": chunk_diag.get("noise_sensitivity"),
        "self_knowledge_ratio": chunk_diag.get("self_knowledge_ratio"),
        "chunk_diag_counts": chunk_diag.get("counts") if isinstance(chunk_diag.get("counts"), dict) else None,
        "expected_refusal": expected_refusal,
        "reasoning_hops_count": int(len(reasoning_hops)),
        "evidence_chain_steps": int(len(evidence_chain)),
        "multihop_enabled": bool(multihop.get("enabled")),
        "multihop_path_completeness": multihop.get("path_completeness"),
        "multihop_order_consistency": multihop.get("order_consistency"),
        "multihop_chain_hit": multihop.get("chain_hit"),
    }
    if retrieval_effective_context_rate is None:
        for key in (
            "retrieval_effective_context_rate",
            "retrieval_noise_rate",
            "retrieval_effective_records",
            "retrieval_evaluated_records",
        ):
            meta.pop(key, None)
    if citation_eval_limit is not None:
        meta.update(
            {
                "citation_eval_limit": int(citation_eval_limit),
                "citation_total_count": int(len(citations_ranked_all)),
                "citation_evaluated_count": int(len(citations_ranked)),
            }
        )
    if expected_metadata:
        meta.update(_expected_metadata_metrics(expected_metadata=expected_metadata, citations=citations_ranked))

    # Per-case explanations (P0): numeric-only, PII-minimal (safe for bundle exports).
    try:
        explanations: dict[str, str] = {}
        counts = meta.get("chunk_diag_counts") if isinstance(meta.get("chunk_diag_counts"), dict) else {}
        ct = int(counts.get("claims_total") or 0)
        cs = int(counts.get("claims_supported") or 0)
        cn = int(counts.get("claims_noisy") or 0)
        cct = int(counts.get("claims_correct_total") or 0)
        ccu = int(counts.get("claims_correct_uncited") or 0)
        kt = int(counts.get("chunks_total") or 0)
        ku = int(counts.get("chunks_used") or 0)

        if ct > 0:
            explanations["chunk_attribution"] = f"claims_supported={cs}/{ct}"
        if kt > 0:
            explanations["chunk_utilization"] = f"chunks_used={ku}/{kt}"
        if meta.get("noise_sensitivity") is not None and cs > 0:
            explanations["noise_sensitivity"] = f"noise_claims={cn}/{cs}"
        if meta.get("self_knowledge_ratio") is not None and cct > 0:
            explanations["self_knowledge_ratio"] = f"correct_uncited={ccu}/{cct}"
        if meta.get("faithfulness_det") is not None and ct > 0:
            explanations["faithfulness_det"] = f"claims_supported={cs}/{ct} (deterministic)"
        if meta.get("citation_accuracy") is not None and citations_ranked:
            citation_msg = f"relevant_citations={sum(1 for rel in relevance_flags if rel)}/{len(citations_ranked)}"
            if citation_eval_limit is not None:
                citation_msg = (
                    f"{citation_msg}, evaluated_top={int(citation_eval_limit)}, total={len(citations_ranked_all)}"
                )
            explanations["citation_accuracy"] = citation_msg
        if meta.get("quote_verifiability") is not None:
            explanations["quote_verifiability"] = "quoted_spans_checked_against_retrieved_contexts"
        if retrieval_recall is not None and ref_total is not None and matched_refs is not None:
            missed = int(ref_total) - int(matched_refs)
            suffix = f", missed={missed}" if missed >= 0 else ""
            msg = f"ref_sources={int(ref_total)}, matched={int(matched_refs)}{suffix}"
            if missed_ref_ids:
                msg = msg + f", missed_ids={missed_ref_ids[:3]}"
            explanations["retrieval_recall"] = msg[:220]
        if retrieval_effective_context_rate is not None and retrieval_evaluated_records is not None:
            explanations["retrieval_effective_context_rate"] = (
                f"effective_records={int(retrieval_effective_records or 0)}/{int(retrieval_evaluated_records)}"
            )
        if expected_metadata and meta.get("expected_metadata_recall") is not None:
            explanations["expected_metadata"] = (
                f"fields_matched={int(meta.get('expected_metadata_fields_matched') or 0)}/"
                f"{int(meta.get('expected_metadata_fields_total') or 0)}"
            )

        if explanations:
            meta["explanations"] = explanations
    except Exception as exc:
        logger.debug("Ignoring non-critical regression sample fallback failure: %s", exc)

    # Per-item refusal correctness (only when expected_refusal is labeled).
    try:
        abst = meta.get("abstain_triggered")
        exp = meta.get("expected_refusal")
        if isinstance(exp, bool) and abst is not None:
            meta["refusal_correct"] = bool(bool(exp) == bool(abst))
    except Exception as exc:
        logger.debug("Ignoring non-critical regression sample fallback failure: %s", exc)

    sample_kwargs = {
        "user_input": question,
        "response": response,
        "retrieved_contexts": retrieved_contexts,
        "reference": reference,
        "reference_context_ids": reference_context_ids,
        "retrieved_context_ids": retrieved_context_ids,
        "reference_contexts": reference_contexts,
    }

    return sample_kwargs, meta


def build_regression_item_meta(*, sample_kwargs: dict[str, Any] | None, item_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Prepare a JSON-safe meta payload for RagasRegressionItem storage."""
    sample = dict(sample_kwargs or {})
    meta = dict(item_meta or {})

    out = {
        "reference_context_ids": list(sample.get("reference_context_ids") or []),
        "retrieved_context_ids": list(sample.get("retrieved_context_ids") or []),
        # Slice keys for report slicing (best-effort; derived from evidence document metadata).
        "slice_file_type": meta.get("slice_file_type"),
        "slice_language": meta.get("slice_language"),
        "slice_directory": meta.get("slice_directory"),
        "slice_hit_type": meta.get("slice_hit_type"),
        "slice_modality": meta.get("slice_modality"),
        "golden_multimodal_slice": meta.get("golden_multimodal_slice"),
        "slice_quality_bucket": meta.get("slice_quality_bucket"),
        "slice_parse_quality": meta.get("slice_parse_quality"),
        "slice_chunk_quality": meta.get("slice_chunk_quality"),
        "slice_pipeline_hash": meta.get("slice_pipeline_hash"),
        # Multi-modal injection/debug metadata (best-effort).
        "multimodal_router": meta.get("multimodal_router"),
        "tag_meta": meta.get("tag_meta"),
        "image_meta": meta.get("image_meta"),
        "abstain_triggered": meta.get("abstain_triggered"),
        "abstain_reason": meta.get("abstain_reason"),
        "top_relevance_score": meta.get("top_relevance_score"),
        "retrieval_recall": meta.get("retrieval_recall"),
        "retrieval_hit": meta.get("retrieval_hit"),
        "retrieval_mrr": meta.get("retrieval_mrr"),
        "retrieval_ndcg_at_10": meta.get("retrieval_ndcg_at_10"),
        "retrieval_ndcg_at_20": meta.get("retrieval_ndcg_at_20"),
        "retrieval_hit_at_1": meta.get("retrieval_hit_at_1"),
        "retrieval_hit_at_3": meta.get("retrieval_hit_at_3"),
        "retrieval_hit_at_5": meta.get("retrieval_hit_at_5"),
        "retrieval_hit_at_10": meta.get("retrieval_hit_at_10"),
        "retrieval_hit_at_20": meta.get("retrieval_hit_at_20"),
        "citation_accuracy": meta.get("citation_accuracy"),
        "citation_coverage": meta.get("citation_coverage"),
        "citation_eval_limit": meta.get("citation_eval_limit"),
        "citation_total_count": meta.get("citation_total_count"),
        "citation_evaluated_count": meta.get("citation_evaluated_count"),
        "quote_verifiability": meta.get("quote_verifiability"),
        # Answer-level deterministic gate signals (best-effort; may be null in retrieval-only mode).
        "atomic_faithfulness": meta.get("atomic_faithfulness"),
        "hallucination_rate": meta.get("hallucination_rate"),
        "faithfulness_det": meta.get("faithfulness_det"),
        "chunk_utilization": meta.get("chunk_utilization"),
        "chunk_attribution": meta.get("chunk_attribution"),
        "noise_sensitivity": meta.get("noise_sensitivity"),
        "self_knowledge_ratio": meta.get("self_knowledge_ratio"),
        "chunk_diag_counts": meta.get("chunk_diag_counts"),
        "explanations": meta.get("explanations"),
        "expected_refusal": meta.get("expected_refusal"),
        "refusal_correct": meta.get("refusal_correct"),
        # LLM-as-judge (optional; enabled per regression run).
        "llm_judge": meta.get("llm_judge"),
    }
    for key in (
        "retrieval_effective_context_rate",
        "retrieval_noise_rate",
        "retrieval_effective_records",
        "retrieval_evaluated_records",
    ):
        if key in meta:
            out[key] = meta.get(key)
    for key in (
        "expected_metadata_hit",
        "expected_metadata_recall",
        "expected_metadata_fields_total",
        "expected_metadata_fields_matched",
        "expected_metadata_missing_keys",
    ):
        if key in meta:
            out[key] = meta.get(key)
    return out
