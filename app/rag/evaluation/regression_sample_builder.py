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
_SEMANTIC_KEYS_METADATA_KEY = "semantic_keys"
_SEMANTIC_OVERLAP_METADATA_KEYS = {_SEMANTIC_KEYS_METADATA_KEY}


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


def _string_set(value: Any) -> set[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    out: set[str] = set()
    for item in values:
        if not _value_present(item):
            continue
        text = str(item).strip()
        if text:
            out.add(text)
    return out


def _semantic_key_set_from_mapping(value: Any) -> set[str]:
    d = _coerce_dict(value)
    return _string_set(d.get(_SEMANTIC_KEYS_METADATA_KEY))


def _semantic_key_set(obj: Any) -> set[str]:
    out = set(_semantic_key_set_from_mapping(obj))
    for base in _citation_metadata_bases(obj):
        out.update(_semantic_key_set_from_mapping(base))
    for meta in _citation_metadata_containers(obj):
        out.update(_semantic_key_set_from_mapping(meta))
    return out


def _semantic_values_match(expected: Any, actual: Any) -> bool:
    expected_values = _string_set(expected)
    actual_values = _string_set(actual)
    return bool(expected_values and actual_values and expected_values & actual_values)


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


def _metadata_field_matches(key: str, expected: Any, actual: Any) -> bool:
    if key in _SEMANTIC_OVERLAP_METADATA_KEYS:
        return _semantic_values_match(expected, actual)
    return _values_match(expected, actual)


def _citation_metadata_field_matches(citation: Any, key: str, expected: Any) -> bool:
    if key in _SEMANTIC_OVERLAP_METADATA_KEYS:
        return _semantic_values_match(expected, _semantic_key_set(citation))
    return any(
        _metadata_field_matches(key, expected, _metadata_value(meta, key))
        for meta in _citation_metadata_containers(citation)
    )


def _citation_matches_expected_metadata(citation: Any, expected_metadata: dict[str, Any]) -> bool:
    if not expected_metadata:
        return False
    for key, expected_value in expected_metadata.items():
        if not _citation_metadata_field_matches(citation, key, expected_value):
            return False
    return True


def _expected_metadata_metrics(*, expected_metadata: dict[str, Any], citations: list[Any]) -> dict[str, Any]:
    if not expected_metadata:
        return {}

    matched_keys: set[str] = set()
    for key, expected_value in expected_metadata.items():
        for citation in citations or []:
            if _citation_metadata_field_matches(citation, key, expected_value):
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


def _citation_eval_limit(item: dict[str, Any]) -> int | None:
    raw_citation_eval_limit = item.get("citation_eval_limit")
    if raw_citation_eval_limit is None:
        return None
    try:
        parsed_limit = int(raw_citation_eval_limit)
    except (TypeError, ValueError):
        parsed_limit = 0
    return parsed_limit if parsed_limit > 0 else None


def _ranked_citations(
    citations: list[Any], *, citation_eval_limit: int | None
) -> tuple[list[Any], list[str], list[Any]]:
    citations_ranked_all: list[Any] = []
    seen_cids: set[str] = set()
    for citation in citations or []:
        data = _coerce_dict(citation)
        cid = str(data.get("chunk_id") or "").strip()
        if not cid or cid in seen_cids:
            continue
        seen_cids.add(cid)
        citations_ranked_all.append(citation)
    citations_ranked = (
        citations_ranked_all[:citation_eval_limit] if citation_eval_limit is not None else citations_ranked_all
    )
    return citations_ranked_all, _dedup_ids(citations_ranked, key="chunk_id"), citations_ranked


def _reference_match_state(
    *,
    reference_sources: list[Any],
    citations_ranked: list[Any],
    reference_context_ids: list[str],
    retrieved_context_ids: list[str],
    expected_semantic_keys: set[str],
) -> dict[str, Any]:
    ref_semantic_key_sets: list[set[str]] = []
    ref_quotes: list[str] = []
    ref_keys = [key for src in reference_sources if (key := _stable_ref_key(src))]
    ref_record_keys = [key for src in reference_sources if (key := _record_identity_key(src))]
    for src in reference_sources:
        semantic_keys = _semantic_key_set(src)
        if semantic_keys:
            ref_semantic_key_sets.append(semantic_keys)
        qsig = _quote_signature(_coerce_dict(src).get("quote"))
        if qsig:
            ref_quotes.append(qsig)
    fallback_semantic_key_set = (
        expected_semantic_keys if expected_semantic_keys and not ref_semantic_key_sets else set()
    )
    if fallback_semantic_key_set:
        ref_semantic_key_sets.append(fallback_semantic_key_set)

    cit_semantic_key_sets = [_semantic_key_set(citation) for citation in citations_ranked]
    cit_texts = [_citation_text_for_quote_match(citation) for citation in citations_ranked]
    return {
        "ref_set": set(reference_context_ids or []),
        "ret_set": set(retrieved_context_ids or []),
        "ref_key_set": set(ref_keys),
        "ref_record_key_set": set(ref_record_keys),
        "ref_semantic_key_sets": ref_semantic_key_sets,
        "ref_quotes": ref_quotes,
        "fallback_semantic_key_set": fallback_semantic_key_set,
        "cit_key_set": {key for citation in citations_ranked if (key := _stable_citation_key(citation))},
        "cit_record_key_set": {key for citation in citations_ranked if (key := _record_identity_key(citation))},
        "cit_semantic_key_sets": cit_semantic_key_sets,
        "cit_semantic_key_union": {key for keys in cit_semantic_key_sets for key in keys},
        "cit_text_joined": "\n".join([text for text in cit_texts if text]) if cit_texts else "",
    }


def _quote_matches_any_reference(citation: Any, ref_quotes: list[str]) -> bool:
    if not ref_quotes:
        return False
    text = _citation_text_for_quote_match(citation)
    return bool(text and any(qsig and qsig in text for qsig in ref_quotes))


def _citation_matches_reference(citation: Any, *, semantic_keys: set[str], state: dict[str, Any]) -> bool:
    data = _coerce_dict(citation)
    cid = str(data.get("chunk_id") or "").strip()
    if cid and cid in state["ref_set"]:
        return True
    citation_key = _stable_citation_key(data)
    if citation_key and citation_key in state["ref_key_set"]:
        return True
    record_key = _record_identity_key(data)
    if record_key and record_key in state["ref_record_key_set"]:
        return True
    if semantic_keys and any(semantic_keys & ref_keys for ref_keys in state["ref_semantic_key_sets"]):
        return True
    return _quote_matches_any_reference(data, state["ref_quotes"])


def _reference_source_matched(src: Any, *, state: dict[str, Any]) -> bool:
    data = _coerce_dict(src)
    cid = str(data.get("chunk_id") or "").strip()
    if cid and cid in state["ret_set"]:
        return True
    source_key = _stable_ref_key(src)
    if source_key and source_key in state["cit_key_set"]:
        return True
    record_key = _record_identity_key(src)
    if record_key and record_key in state["cit_record_key_set"]:
        return True
    src_semantic_keys = _semantic_key_set(src) or state["fallback_semantic_key_set"]
    if src_semantic_keys and state["cit_semantic_key_union"] and src_semantic_keys & state["cit_semantic_key_union"]:
        return True
    qsig = _quote_signature(data.get("quote"))
    return bool(qsig and state["cit_text_joined"] and qsig in state["cit_text_joined"])


def _ranked_relevance_flags(citations_ranked: list[Any], *, state: dict[str, Any]) -> list[bool]:
    semantic_key_sets = state["cit_semantic_key_sets"]
    flags: list[bool] = []
    for index, citation in enumerate(citations_ranked):
        semantic_keys = semantic_key_sets[index] if index < len(semantic_key_sets) else _semantic_key_set(citation)
        flags.append(_citation_matches_reference(citation, semantic_keys=semantic_keys, state=state))
    return flags


def _ndcg_at(relevance_flags: list[bool], *, ref_total: int, k: int) -> float:
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


def _hit_at(relevance_flags: list[bool], *, k: int) -> bool:
    kk = max(0, int(k or 0))
    return any(relevance_flags[:kk]) if kk > 0 else False


def _document_recall_metrics(
    reference_sources: list[Any], citations_ranked: list[Any]
) -> tuple[float | None, bool | None]:
    ref_doc_set = {str(_coerce_dict(src).get("document_id") or "").strip() for src in reference_sources}
    ref_doc_set = {doc_id for doc_id in ref_doc_set if doc_id}
    if not ref_doc_set:
        return None, None
    cit_doc_set = {str(_coerce_dict(citation).get("document_id") or "").strip() for citation in citations_ranked}
    cit_doc_set = {doc_id for doc_id in cit_doc_set if doc_id}
    matched_docs = int(len(ref_doc_set & cit_doc_set))
    return round(float(matched_docs) / max(1, int(len(ref_doc_set))), 4), bool(matched_docs > 0)


def _family_recall_metrics(
    reference_sources: list[Any], citations_ranked: list[Any]
) -> tuple[float | None, bool | None]:
    ref_fam_set = {family for family in (_family_key(src) for src in reference_sources) if family}
    if not ref_fam_set:
        return None, None
    cit_fam_set = {family for family in (_family_key(citation) for citation in citations_ranked) if family}
    matched_fams = int(len(ref_fam_set & cit_fam_set))
    return round(float(matched_fams) / max(1, int(len(ref_fam_set))), 4), bool(matched_fams > 0)


def _missed_reference_ids(reference_sources: list[Any], *, state: dict[str, Any]) -> list[str]:
    missed: list[str] = []
    for src in reference_sources:
        if _reference_source_matched(src, state=state):
            continue
        stable_key = _stable_ref_key(src)
        fallback = str(_coerce_dict(src).get("chunk_id") or "").strip()
        raw_id = stable_key or fallback
        if not raw_id:
            continue
        missed.append(stable_hash(raw_id, length=16))
        if len(missed) >= 6:
            break
    return missed


def _retrieval_metrics(
    *,
    reference_sources: list[Any],
    citations_ranked: list[Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "retrieval_recall": None,
        "retrieval_hit": None,
        "retrieval_mrr": None,
        "retrieval_ndcg_at_10": None,
        "retrieval_ndcg_at_20": None,
        "retrieval_hit_at_1": None,
        "retrieval_hit_at_3": None,
        "retrieval_hit_at_5": None,
        "retrieval_hit_at_10": None,
        "retrieval_hit_at_20": None,
        "retrieval_doc_recall": None,
        "retrieval_doc_hit": None,
        "retrieval_family_recall": None,
        "retrieval_family_hit": None,
        "relevance_flags": [],
        "ref_total": None,
        "matched_refs": None,
        "missed_ref_ids": [],
    }
    if not reference_sources:
        return metrics
    ref_total = len(reference_sources)
    matched_refs = sum(1 for src in reference_sources if _reference_source_matched(src, state=state))
    relevance_flags = _ranked_relevance_flags(citations_ranked, state=state)
    rank_first = next((index + 1 for index, rel in enumerate(relevance_flags) if rel), None)
    retrieval_doc_recall, retrieval_doc_hit = _document_recall_metrics(reference_sources, citations_ranked)
    retrieval_family_recall, retrieval_family_hit = _family_recall_metrics(reference_sources, citations_ranked)
    metrics.update(
        {
            "retrieval_recall": round(float(matched_refs) / max(1, int(ref_total)), 4),
            "retrieval_hit": bool(matched_refs > 0),
            "retrieval_mrr": round(1.0 / float(rank_first), 4) if rank_first else 0.0,
            "retrieval_ndcg_at_10": _ndcg_at(relevance_flags, ref_total=ref_total, k=10),
            "retrieval_ndcg_at_20": _ndcg_at(relevance_flags, ref_total=ref_total, k=20),
            "retrieval_hit_at_1": _hit_at(relevance_flags, k=1),
            "retrieval_hit_at_3": _hit_at(relevance_flags, k=3),
            "retrieval_hit_at_5": _hit_at(relevance_flags, k=5),
            "retrieval_hit_at_10": _hit_at(relevance_flags, k=10),
            "retrieval_hit_at_20": _hit_at(relevance_flags, k=20),
            "retrieval_doc_recall": retrieval_doc_recall,
            "retrieval_doc_hit": retrieval_doc_hit,
            "retrieval_family_recall": retrieval_family_recall,
            "retrieval_family_hit": retrieval_family_hit,
            "relevance_flags": relevance_flags,
            "ref_total": ref_total,
            "matched_refs": matched_refs,
            "missed_ref_ids": _missed_reference_ids(reference_sources, state=state),
        }
    )
    return metrics


def _effective_context_metrics(
    *,
    answer_key_points: list[str],
    answer_key_point_aliases: dict[str, list[str]],
    citations_ranked: list[Any],
    retrieved_contexts: list[Any],
) -> dict[str, Any]:
    metrics = {
        "retrieval_effective_context_rate": None,
        "retrieval_noise_rate": None,
        "retrieval_effective_records": None,
        "retrieval_evaluated_records": None,
    }
    if not answer_key_points or not citations_ranked:
        return metrics
    effective_flags: list[bool] = []
    for index, citation in enumerate(citations_ranked):
        text_parts = [_citation_text_for_quote_match(citation)]
        if index < len(retrieved_contexts):
            text_parts.append(_collapse_ws(retrieved_contexts[index]).casefold())
        text = "\n".join(part for part in text_parts if part)
        effective_flags.append(
            any(_answer_key_point_in_text(point, text, answer_key_point_aliases) for point in answer_key_points)
        )
    evaluated = int(len(effective_flags))
    effective = int(sum(1 for flag in effective_flags if flag))
    rate = round(float(effective) / max(1, evaluated), 4)
    metrics.update(
        {
            "retrieval_effective_context_rate": rate,
            "retrieval_noise_rate": round(1.0 - rate, 4),
            "retrieval_effective_records": effective,
            "retrieval_evaluated_records": evaluated,
        }
    )
    return metrics


def _reference_evidence_text(reference: str, reference_contexts: list[str]) -> str | None:
    ref_evidence_parts: list[str] = []
    if reference.strip():
        ref_evidence_parts.append(reference.strip())
    ref_evidence_parts.extend([str(text or "").strip() for text in reference_contexts if str(text or "").strip()])
    return "\n".join(ref_evidence_parts).strip() or None


def _reasoning_inputs(case: Any, extra_d: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    reasoning_hops_raw = _get(case, "reasoning_hops", None)
    if not isinstance(reasoning_hops_raw, list):
        reasoning_hops_raw = extra_d.get("reasoning_hops")
    reasoning_hops = [str(value) for value in (reasoning_hops_raw or []) if str(value or "").strip()][:20]
    evidence_chain_raw = _get(case, "evidence_chain", None)
    if not isinstance(evidence_chain_raw, list):
        evidence_chain_raw = extra_d.get("evidence_chain")
    evidence_chain: list[dict[str, Any]] = []
    for item_raw in evidence_chain_raw or []:
        row = _coerce_dict(item_raw)
        if row:
            evidence_chain.append(row)
        if len(evidence_chain) >= 20:
            break
    return reasoning_hops, evidence_chain


def _expected_refusal(extra_d: dict[str, Any]) -> bool | None:
    for key in ("expected_refusal", "should_refuse", "expected_abstain"):
        if key in extra_d:
            return bool(extra_d.get(key))
    return None


def _build_explanations(
    *,
    meta: dict[str, Any],
    citations_ranked: list[Any],
    citation_eval_limit: int | None,
    citations_ranked_all: list[Any],
    relevance_flags: list[bool],
    retrieval_metrics: dict[str, Any],
    expected_metadata: dict[str, Any],
) -> dict[str, str]:
    explanations = _chunk_metric_explanations(meta)
    explanations.update(
        _retrieval_metric_explanations(
            meta=meta,
            citations_ranked=citations_ranked,
            citation_eval_limit=citation_eval_limit,
            citations_ranked_all=citations_ranked_all,
            relevance_flags=relevance_flags,
            retrieval_metrics=retrieval_metrics,
            expected_metadata=expected_metadata,
        )
    )
    return explanations


def _chunk_metric_explanations(meta: dict[str, Any]) -> dict[str, str]:
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
    if meta.get("quote_verifiability") is not None:
        explanations["quote_verifiability"] = "quoted_spans_checked_against_retrieved_contexts"
    return explanations


def _retrieval_metric_explanations(
    *,
    meta: dict[str, Any],
    citations_ranked: list[Any],
    citation_eval_limit: int | None,
    citations_ranked_all: list[Any],
    relevance_flags: list[bool],
    retrieval_metrics: dict[str, Any],
    expected_metadata: dict[str, Any],
) -> dict[str, str]:
    explanations: dict[str, str] = {}
    if meta.get("citation_accuracy") is not None and citations_ranked:
        citation_msg = f"relevant_citations={sum(1 for rel in relevance_flags if rel)}/{len(citations_ranked)}"
        if citation_eval_limit is not None:
            citation_msg = (
                f"{citation_msg}, evaluated_top={int(citation_eval_limit)}, total={len(citations_ranked_all)}"
            )
        explanations["citation_accuracy"] = citation_msg
    ref_total = retrieval_metrics.get("ref_total")
    matched_refs = retrieval_metrics.get("matched_refs")
    if meta.get("retrieval_recall") is not None and ref_total is not None and matched_refs is not None:
        missed = int(ref_total) - int(matched_refs)
        suffix = f", missed={missed}" if missed >= 0 else ""
        msg = f"ref_sources={int(ref_total)}, matched={int(matched_refs)}{suffix}"
        missed_ref_ids = retrieval_metrics.get("missed_ref_ids") or []
        if missed_ref_ids:
            msg = msg + f", missed_ids={missed_ref_ids[:3]}"
        explanations["retrieval_recall"] = msg[:220]
    if meta.get("retrieval_effective_context_rate") is not None and meta.get("retrieval_evaluated_records") is not None:
        explanations["retrieval_effective_context_rate"] = (
            f"effective_records={int(meta.get('retrieval_effective_records') or 0)}/"
            f"{int(meta.get('retrieval_evaluated_records') or 0)}"
        )
    if expected_metadata and meta.get("expected_metadata_recall") is not None:
        explanations["expected_metadata"] = (
            f"fields_matched={int(meta.get('expected_metadata_fields_matched') or 0)}/"
            f"{int(meta.get('expected_metadata_fields_total') or 0)}"
        )
    return explanations


def _reference_contexts(reference_sources: list[Any]) -> list[str]:
    contexts: list[str] = []
    for src in reference_sources:
        quote = str(_coerce_dict(src).get("quote") or "").strip()
        if quote:
            contexts.append(quote)
    return contexts


def _parse_top_relevance_score(item: dict[str, Any]) -> float | None:
    top_rel = item.get("top_relevance_score")
    try:
        return float(top_rel) if top_rel is not None else None
    except Exception:
        return None


def _context_relevance_flags(
    reference_sources: list[Any], retrieved_contexts: list[Any], relevance_flags: list[bool]
) -> list[bool] | None:
    if not reference_sources:
        return None
    return [
        bool(relevance_flags[i]) if i < len(relevance_flags) else False for i in range(len(retrieved_contexts or []))
    ]


def _drop_effective_context_fields(meta: dict[str, Any], *, enabled: bool) -> None:
    if enabled:
        return
    for key in (
        "retrieval_effective_context_rate",
        "retrieval_noise_rate",
        "retrieval_effective_records",
        "retrieval_evaluated_records",
    ):
        meta.pop(key, None)


def _attach_explanations(
    *,
    meta: dict[str, Any],
    citations_ranked: list[Any],
    citation_eval_limit: int | None,
    citations_ranked_all: list[Any],
    relevance_flags: list[bool],
    retrieval_metrics: dict[str, Any],
    expected_metadata: dict[str, Any],
) -> None:
    try:
        explanations = _build_explanations(
            meta=meta,
            citations_ranked=citations_ranked,
            citation_eval_limit=citation_eval_limit,
            citations_ranked_all=citations_ranked_all,
            relevance_flags=relevance_flags,
            retrieval_metrics=retrieval_metrics,
            expected_metadata=expected_metadata,
        )
        if explanations:
            meta["explanations"] = explanations
    except Exception as exc:
        logger.debug("Ignoring non-critical regression sample fallback failure: %s", exc)


def _apply_refusal_correctness(meta: dict[str, Any]) -> None:
    try:
        abst = meta.get("abstain_triggered")
        exp = meta.get("expected_refusal")
        if isinstance(exp, bool) and abst is not None:
            meta["refusal_correct"] = bool(bool(exp) == bool(abst))
    except Exception as exc:
        logger.debug("Ignoring non-critical regression sample fallback failure: %s", exc)


def _sample_kwargs(
    *,
    question: str,
    response: str,
    retrieved_contexts: list[Any],
    reference: str,
    reference_context_ids: list[str],
    retrieved_context_ids: list[str],
    reference_contexts: list[str],
) -> dict[str, Any]:
    return {
        "user_input": question,
        "response": response,
        "retrieved_contexts": retrieved_contexts,
        "reference": reference,
        "reference_context_ids": reference_context_ids,
        "retrieved_context_ids": retrieved_context_ids,
        "reference_contexts": reference_contexts,
    }


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
    reference_contexts = _reference_contexts(reference_sources)

    citations = item.get("citations") or []
    extra = _get(case, "extra", None)
    extra_d = extra if isinstance(extra, dict) else {}
    expected_metadata = _expected_metadata_from_case_extra(extra_d)
    expected_semantic_keys = _string_set(expected_metadata.get(_SEMANTIC_KEYS_METADATA_KEY))
    answer_key_points = _answer_key_points_from_case_extra(extra_d)
    answer_key_point_aliases = _answer_key_point_aliases_from_case_extra(extra_d)
    citation_eval_limit = _citation_eval_limit(item)
    citations_ranked_all, retrieved_context_ids, citations_ranked = _ranked_citations(
        citations,
        citation_eval_limit=citation_eval_limit,
    )
    match_state = _reference_match_state(
        reference_sources=reference_sources,
        citations_ranked=citations_ranked,
        reference_context_ids=reference_context_ids,
        retrieved_context_ids=retrieved_context_ids,
        expected_semantic_keys=expected_semantic_keys,
    )
    retrieval_metrics = _retrieval_metrics(
        reference_sources=reference_sources,
        citations_ranked=citations_ranked,
        state=match_state,
    )
    relevance_flags = retrieval_metrics["relevance_flags"]
    citation_accuracy = (
        round(float(sum(1 for rel in relevance_flags if rel)) / float(len(citations_ranked)), 4)
        if reference_sources and citations_ranked
        else None
    )
    effective_metrics = _effective_context_metrics(
        answer_key_points=answer_key_points,
        answer_key_point_aliases=answer_key_point_aliases,
        citations_ranked=citations_ranked,
        retrieved_contexts=retrieved_contexts,
    )
    citation_coverage = retrieval_metrics["retrieval_recall"]

    top_rel_f = _parse_top_relevance_score(item)

    expected_refusal = _expected_refusal(extra_d)

    faithfulness_det = _deterministic_faithfulness(response, retrieved_contexts)
    atomic_faithfulness = faithfulness_det
    hallucination_rate = round(1.0 - float(faithfulness_det), 4) if faithfulness_det is not None else None
    quote_verifiability = _quote_verifiability(response, retrieved_contexts)

    # Chunk-level diagnostics (P0): attribution/utilization/noise/self-knowledge.
    reference_evidence_text = _reference_evidence_text(reference, reference_contexts)

    context_relevance = _context_relevance_flags(reference_sources, retrieved_contexts, relevance_flags)

    chunk_diag = compute_chunk_diagnostics(
        answer=response,
        retrieved_contexts=[str(c or "") for c in (retrieved_contexts or [])],
        context_relevance=context_relevance,
        reference_evidence_text=reference_evidence_text,
    )

    reasoning_hops, evidence_chain = _reasoning_inputs(case, extra_d)

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
        "retrieval_recall": retrieval_metrics["retrieval_recall"],
        "retrieval_hit": retrieval_metrics["retrieval_hit"],
        "retrieval_mrr": retrieval_metrics["retrieval_mrr"],
        "retrieval_ndcg_at_10": retrieval_metrics["retrieval_ndcg_at_10"],
        "retrieval_ndcg_at_20": retrieval_metrics["retrieval_ndcg_at_20"],
        "retrieval_hit_at_1": retrieval_metrics["retrieval_hit_at_1"],
        "retrieval_hit_at_3": retrieval_metrics["retrieval_hit_at_3"],
        "retrieval_hit_at_5": retrieval_metrics["retrieval_hit_at_5"],
        "retrieval_hit_at_10": retrieval_metrics["retrieval_hit_at_10"],
        "retrieval_hit_at_20": retrieval_metrics["retrieval_hit_at_20"],
        "retrieval_doc_recall": retrieval_metrics["retrieval_doc_recall"],
        "retrieval_doc_hit": retrieval_metrics["retrieval_doc_hit"],
        "retrieval_family_recall": retrieval_metrics["retrieval_family_recall"],
        "retrieval_family_hit": retrieval_metrics["retrieval_family_hit"],
        "citation_accuracy": citation_accuracy,
        "citation_coverage": citation_coverage,
        "retrieval_effective_context_rate": effective_metrics["retrieval_effective_context_rate"],
        "retrieval_noise_rate": effective_metrics["retrieval_noise_rate"],
        "retrieval_effective_records": effective_metrics["retrieval_effective_records"],
        "retrieval_evaluated_records": effective_metrics["retrieval_evaluated_records"],
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
    _drop_effective_context_fields(meta, enabled=effective_metrics["retrieval_effective_context_rate"] is not None)
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

    _attach_explanations(
        meta=meta,
        citations_ranked=citations_ranked,
        citation_eval_limit=citation_eval_limit,
        citations_ranked_all=citations_ranked_all,
        relevance_flags=relevance_flags,
        retrieval_metrics=retrieval_metrics,
        expected_metadata=expected_metadata,
    )
    _apply_refusal_correctness(meta)

    return _sample_kwargs(
        question=question,
        response=response,
        retrieved_contexts=retrieved_contexts,
        reference=reference,
        reference_context_ids=reference_context_ids,
        retrieved_context_ids=retrieved_context_ids,
        reference_contexts=reference_contexts,
    ), meta


def build_regression_item_meta(
    *, sample_kwargs: dict[str, Any] | None, item_meta: dict[str, Any] | None
) -> dict[str, Any]:
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
        "retrieval_doc_recall": meta.get("retrieval_doc_recall"),
        "retrieval_doc_hit": meta.get("retrieval_doc_hit"),
        "retrieval_family_recall": meta.get("retrieval_family_recall"),
        "retrieval_family_hit": meta.get("retrieval_family_hit"),
        "must_recall_passed": meta.get("must_recall_passed"),
        "must_recall_status": meta.get("must_recall_status"),
        "evidence_capsule": meta.get("evidence_capsule"),
        "provenance_integrity_passed": meta.get("provenance_integrity_passed"),
        "provenance_integrity_status": meta.get("provenance_integrity_status"),
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
        "parse_quality_alert",
        "parse_quality_low_ratio",
        "parse_risk_level",
        "parse_risk_score",
        "parse_quality_gate_profile",
        "parse_quality_gate_blocked",
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
