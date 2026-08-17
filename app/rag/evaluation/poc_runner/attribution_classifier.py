from datetime import UTC, datetime
from typing import Any, Callable

from app.rag.evaluation.poc_runner.telemetry import feedback_polarity_from_score

POC_ATTRIBUTION_SCHEMA_V1 = "mimirq.poc.attribution.v1"
_CATEGORIES = ("retrieval_miss", "generation_error", "out_of_scope")


def _safe_str(value: Any, *, max_len: int = 2_000) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[: max(1, int(max_len or 1))]


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _is_negative_feedback(row: dict[str, Any]) -> bool:
    polarity = _safe_str(row.get("feedback_polarity"), max_len=40)
    if polarity is not None:
        return polarity == "negative"
    return feedback_polarity_from_score(row.get("feedback_score")) == "negative"


def heuristic_classify_feedback_record(row: dict[str, Any]) -> dict[str, Any]:
    comment = (_safe_str(row.get("feedback_comment")) or "").casefold()
    query = (_safe_str(row.get("original_query")) or "").casefold()
    answer = (_safe_str(row.get("llm_response")) or "").casefold()
    filenames = row.get("final_context_filenames") or []
    has_files = isinstance(filenames, list) and bool(filenames)
    joined = " ".join(part for part in (comment, query, answer) if part)

    if any(token in joined for token in ("知识库没有", "未收录", "超出知识库", "新型号", "没有相关资料")):
        return {
            "category": "out_of_scope",
            "confidence": 0.88,
            "rationale": "knowledge_gap_signals",
        }
    if not has_files and any(token in joined for token in ("没检索到", "没找到", "找不到", "搜不到", "召回")):
        return {
            "category": "retrieval_miss",
            "confidence": 0.66,
            "rationale": "missing_retrieval_evidence",
        }
    if has_files and any(token in joined for token in ("答非所问", "回答错误", "不正确", "胡说")):
        return {
            "category": "generation_error",
            "confidence": 0.82,
            "rationale": "evidence_present_but_answer_failed",
        }
    if has_files:
        return {
            "category": "generation_error",
            "confidence": 0.72,
            "rationale": "answer_quality_fallback",
        }
    return {
        "category": "retrieval_miss",
        "confidence": 0.6,
        "rationale": "negative_feedback_without_context",
    }


def _build_llm_prompt(row: dict[str, Any]) -> str:
    filenames = ", ".join(
        str(name or "").strip() for name in (row.get("final_context_filenames") or []) if str(name or "").strip()
    )
    return (
        "Classify the root cause of this negative feedback into one of: "
        "retrieval_miss, generation_error, out_of_scope.\n"
        "Return a JSON object with keys: category, confidence, rationale.\n\n"
        f"User question:\n{_safe_str(row.get('original_query')) or ''}\n\n"
        f"System answer:\n{_safe_str(row.get('llm_response')) or ''}\n\n"
        f"User feedback:\n{_safe_str(row.get('feedback_comment')) or ''}\n\n"
        f"Retrieved documents:\n{filenames or '(none)'}\n"
    )


def build_llm_attribution_classifier(
    llm_callable: Callable[[str], dict[str, Any]],
    *,
    fallback_classifier: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    fallback = fallback_classifier or heuristic_classify_feedback_record

    def _classifier(row: dict[str, Any]) -> dict[str, Any]:
        prompt = _build_llm_prompt(row)
        try:
            raw = dict(llm_callable(prompt) or {})
        except Exception:
            return dict(fallback(row) or {})

        category = _safe_str(raw.get("category"), max_len=40) or ""
        try:
            confidence = round(float(raw.get("confidence") or 0.0), 4)
        except Exception:
            confidence = 0.0
        rationale = _safe_str(raw.get("rationale"), max_len=255) or "llm_unspecified"

        if category not in _CATEGORIES or confidence <= 0.0:
            return dict(fallback(row) or {})

        return {
            "category": category,
            "confidence": confidence,
            "rationale": rationale,
        }

    return _classifier


def _top_example_sort_key(example: dict[str, Any]) -> tuple[float, float, str]:
    confidence = float(example.get("confidence") or 0.0)
    created_at = _coerce_datetime(example.get("created_at"))
    created_ts = created_at.timestamp() if created_at is not None else 0.0
    interaction_id = str(example.get("interaction_id") or "")
    return (confidence, created_ts, interaction_id)


def classify_feedback_records(
    records: list[dict[str, Any]],
    *,
    classifier: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    review_confidence_threshold: float = 0.7,
    max_examples_per_category: int = 10,
) -> dict[str, Any]:
    selected = [dict(row or {}) for row in (records or []) if isinstance(row, dict) and _is_negative_feedback(row)]
    counts = dict.fromkeys(_CATEGORIES, 0)
    top_examples = {category: [] for category in _CATEGORIES}
    manual_review_candidates: list[dict[str, Any]] = []

    if classifier is None:
        classifier = heuristic_classify_feedback_record

    annotated: list[dict[str, Any]] = []
    for row in selected:
        result = dict(classifier(row) or {})
        category = _safe_str(result.get("category"), max_len=40) or "generation_error"
        if category not in counts:
            category = "generation_error"
        confidence = float(result.get("confidence") or 0.0)
        rationale = _safe_str(result.get("rationale"), max_len=255) or "unspecified"
        example = {
            "interaction_id": _safe_str(row.get("interaction_id"), max_len=255),
            "category": category,
            "confidence": round(confidence, 4),
            "rationale": rationale,
            "created_at": _safe_str(row.get("created_at"), max_len=64),
            "original_query": _safe_str(row.get("original_query")),
            "llm_response": _safe_str(row.get("llm_response")),
            "final_context_filenames": list(row.get("final_context_filenames") or [])[:20],
        }
        annotated.append(example)
        counts[category] += 1
        if confidence < float(review_confidence_threshold):
            manual_review_candidates.append(
                {
                    "interaction_id": example["interaction_id"],
                    "category": category,
                    "confidence": round(confidence, 4),
                    "rationale": rationale,
                }
            )

    for category in _CATEGORIES:
        examples = [item for item in annotated if item["category"] == category]
        examples.sort(key=_top_example_sort_key, reverse=True)
        top_examples[category] = examples[: max(1, int(max_examples_per_category or 1))]

    negative_feedback_count = len(selected)
    ratios = {
        category: (counts[category] / negative_feedback_count if negative_feedback_count else 0.0)
        for category in _CATEGORIES
    }

    return {
        "schema": POC_ATTRIBUTION_SCHEMA_V1,
        "negative_feedback_count": negative_feedback_count,
        "counts": counts,
        "ratios": ratios,
        "top_examples": top_examples,
        "manual_review_candidates": manual_review_candidates,
    }
