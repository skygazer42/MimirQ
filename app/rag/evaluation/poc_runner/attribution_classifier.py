import math
from typing import Any, Callable, TypedDict

from app.rag.evaluation.poc_runner.telemetry import _coerce_datetime, _safe_str, feedback_polarity_from_score

POC_ATTRIBUTION_SCHEMA_V1 = "mimirq.poc.attribution.v1"
_CATEGORIES = ("retrieval_miss", "generation_error", "out_of_scope")


class _AttributionExample(TypedDict):
    interaction_id: str | None
    category: str
    confidence: float
    rationale: str
    created_at: str | None
    original_query: str | None
    llm_response: str | None
    final_context_filenames: list[Any]
    method: str
    error: str | None


def _is_negative_feedback(row: dict[str, Any]) -> bool:
    polarity = _safe_str(row.get("feedback_polarity"), max_len=40)
    if polarity is not None:
        return polarity == "negative"
    return feedback_polarity_from_score(row.get("feedback_score")) == "negative"


def heuristic_classify_feedback_record(row: dict[str, Any]) -> dict[str, Any]:
    comment = _safe_str(row.get("feedback_comment"))
    query = _safe_str(row.get("original_query"))
    answer = _safe_str(row.get("llm_response"))
    filenames = row.get("final_context_filenames") or []
    has_files = isinstance(filenames, list) and bool(filenames)
    joined = " ".join(part.casefold() for part in (comment, query, answer) if part is not None)

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
        str(name).strip()
        for name in (row.get("final_context_filenames") or [])
        if name is not None and str(name).strip()
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
    fallback = heuristic_classify_feedback_record if fallback_classifier is None else fallback_classifier

    def _classifier(row: dict[str, Any]) -> dict[str, Any]:
        prompt = _build_llm_prompt(row)
        try:
            raw = llm_callable(prompt)
            category = _safe_str(raw.get("category"), max_len=40)
            if isinstance(raw["confidence"], bool):
                raise ValueError("confidence must be numeric")
            confidence = float(raw["confidence"])
            if category not in _CATEGORIES or not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                raise ValueError("invalid_llm_attribution_category_or_confidence")
        except Exception as exc:
            return {
                **fallback(row),
                "method": "heuristic_fallback" if fallback_classifier is None else "classifier_fallback",
                "error": f"{type(exc).__name__}:{exc}",
            }
        rationale = _safe_str(raw.get("rationale"), max_len=255) or "llm_unspecified"

        return {
            "category": category,
            "confidence": round(confidence, 4),
            "rationale": rationale,
            "method": "llm",
            "error": None,
        }

    return _classifier


def _top_example_sort_key(example: _AttributionExample) -> tuple[float, float, bool, str | None]:
    confidence = example["confidence"] or 0.0
    created_at = _coerce_datetime(example.get("created_at"))
    created_ts = created_at.timestamp() if created_at is not None else 0.0
    interaction_id = example["interaction_id"]
    return (confidence, created_ts, interaction_id is not None, interaction_id)


def classify_feedback_records(
    records: list[dict[str, Any]],
    *,
    classifier: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    review_confidence_threshold: float = 0.7,
    max_examples_per_category: int = 10,
) -> dict[str, Any]:
    selected = [dict(row) for row in (records or []) if isinstance(row, dict) and _is_negative_feedback(row)]
    counts = dict.fromkeys(_CATEGORIES, 0)
    top_examples: dict[str, list[_AttributionExample]] = {category: [] for category in _CATEGORIES}
    manual_review_candidates: list[dict[str, Any]] = []
    classification_errors: list[dict[str, Any]] = []

    if classifier is None:
        classifier = heuristic_classify_feedback_record

    unclassified_count = 0
    for row in selected:
        result = dict(classifier(row) or {})
        category = _safe_str(result.get("category"), max_len=40)
        error = _safe_str(result.get("error"))
        if category not in counts:
            error = f"invalid_classifier_category:{category}"
            category = "unclassified"
        try:
            if isinstance(result["confidence"], bool):
                raise ValueError("confidence must be numeric")
            confidence = float(result["confidence"])
            if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                raise ValueError("confidence must be finite and in [0,1]")
        except (KeyError, OverflowError, TypeError, ValueError) as exc:
            confidence = 0.0
            error = f"invalid_classifier_confidence:{exc}"
        rationale = _safe_str(result.get("rationale"), max_len=255) or "unspecified"
        example: _AttributionExample = {
            "interaction_id": _safe_str(row.get("interaction_id"), max_len=255),
            "category": category,
            "confidence": round(confidence, 4),
            "rationale": rationale,
            "created_at": _safe_str(row.get("created_at"), max_len=64),
            "original_query": _safe_str(row.get("original_query")),
            "llm_response": _safe_str(row.get("llm_response")),
            "final_context_filenames": list(row.get("final_context_filenames") or [])[:20],
            "method": result.get("method")
            or ("heuristic" if classifier is heuristic_classify_feedback_record else "custom"),
            "error": error,
        }
        if category in counts:
            counts[category] += 1
            top_examples[category].append(example)
        else:
            unclassified_count += 1
        if error is not None:
            classification_errors.append({"interaction_id": example["interaction_id"], "error": error})
        if error is not None or confidence < float(review_confidence_threshold):
            manual_review_candidates.append(
                {
                    "interaction_id": example["interaction_id"],
                    "category": category,
                    "confidence": round(confidence, 4),
                    "rationale": rationale,
                    "method": example["method"],
                    "error": error,
                }
            )

    limit = max(1, int(max_examples_per_category or 1))
    for category, examples in top_examples.items():
        examples.sort(key=_top_example_sort_key, reverse=True)
        top_examples[category] = examples[:limit]

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
        "unclassified_count": unclassified_count,
        "classification_errors": classification_errors,
    }
