
from collections.abc import Iterable
from statistics import median
from typing import Any
from uuid import UUID

from langchain_core.prompts import PromptTemplate

from app.rag.core.hashing import stable_json_hash
from app.rag.core.logging import get_logger
from app.rag.core.text import parse_json_from_text
from app.services.prompt_resolver import resolve_prompt_template

logger = get_logger(__name__)


def clip_text(value: Any, *, max_len: int = 400) -> str:
    text = str(value or "").strip()
    max_len = max(0, int(max_len or 0))
    if not max_len:
        return ""
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3].rstrip()}..."


def clip_contexts_for_judge(
    contexts: Iterable[Any] | None,
    *,
    max_contexts: int = 6,
    max_chars: int = 900,
) -> list[str]:
    cap_ctx = max(1, int(max_contexts or 1))
    cap_chars = max(50, int(max_chars or 50))
    out: list[str] = []
    for raw in contexts or []:
        text = str(raw or "").strip()
        if not text:
            continue
        out.append(text[:cap_chars])
        if len(out) >= cap_ctx:
            break
    return out


def default_llm_judge_prompt(*, kind: str, question: str, answer: str, contexts: list[str]) -> str:
    ctx_lines = "\n".join([f"[C{i + 1}] {item}" for i, item in enumerate(contexts or [])]).strip()
    if kind == "retrieval":
        return (
            "You are a strict evaluator for a RAG system.\n"
            "Evaluate retrieval quality ONLY. Do not judge the final answer.\n\n"
            f"Question:\n{question}\n\n"
            "Retrieved contexts:\n"
            f"{ctx_lines}\n\n"
            "Return STRICT JSON only:\n"
            "{\n"
            '  "score": 0.0,\n'
            '  "reason": "short reason",\n'
            '  "evidence_quotes": ["quote copied verbatim from contexts (<=160 chars)"],\n'
            '  "chunk_judgments": [{"rank": 1, "is_relevant": true, "evidence_quote": "quote"}]\n'
            "}\n\n"
            "Rules:\n"
            "- Use score in [0,1].\n"
            "- evidence_quotes must come from the provided contexts.\n"
            "- Keep reason <= 240 chars.\n"
            "- chunk_judgments may list up to 5 items.\n"
        )

    return (
        "You are a strict evaluator for a RAG system.\n"
        "Evaluate answer quality given the retrieved contexts.\n\n"
        f"Question:\n{question}\n\n"
        f"Answer:\n{answer}\n\n"
        "Retrieved contexts:\n"
        f"{ctx_lines}\n\n"
        "Return STRICT JSON only:\n"
        "{\n"
        '  "score": 0.0,\n'
        '  "reason": "short reason",\n'
        '  "evidence_quotes": ["quote copied verbatim from contexts (<=160 chars)"],\n'
        '  "atomic_facts": [{"fact": "claim", "verdict": "supported", "evidence_quote": "quote"}],\n'
        '  "citation_checks": [{"citation": "ref", "claim": "claim", "verdict": "supported", "evidence_quote": "quote"}]\n'
        "}\n\n"
        "Rules:\n"
        "- Use score in [0,1].\n"
        "- evidence_quotes must come from the provided contexts.\n"
        "- Keep reason <= 240 chars.\n"
        "- verdict should be one of supported|partial|unsupported.\n"
        "- atomic_facts and citation_checks may list up to 5 items each.\n"
    )


def llm_judge_version_hash(
    *,
    model: Any,
    generation_prompt_content: str | None = None,
    generation_prompt_variables: list[str] | None = None,
    generation_prompt_version: int | None = None,
    self_consistency_n: int = 3,
    position_bias_enabled: bool = True,
) -> str:
    model_used = getattr(model, "model_name", None) or getattr(model, "model", None)
    default_inputs = {"question": "{question}", "answer": "{answer}", "contexts": ["{context}"]}
    return stable_json_hash(
        {
            "schema": "mimirq.llm_judge.version.v2",
            "model": str(model_used or ""),
            "temperature": getattr(model, "temperature", None),
            "retrieval_rubric": default_llm_judge_prompt(kind="retrieval", **default_inputs),
            "generation_rubric": generation_prompt_content
            or default_llm_judge_prompt(kind="generation", **default_inputs),
            "generation_prompt_variables": sorted(str(item) for item in (generation_prompt_variables or [])),
            "generation_prompt_version": generation_prompt_version,
            "self_consistency_n": max(1, int(self_consistency_n or 1)),
            "position_bias_enabled": bool(position_bias_enabled),
        },
        length=24,
    )


def render_llm_judge_prompt(
    *,
    kind: str,
    question: str,
    answer: str,
    contexts: list[str],
    prompt_content: str | None = None,
    prompt_variables: list[str] | None = None,
) -> str:
    if kind != "generation" or not str(prompt_content or "").strip():
        return default_llm_judge_prompt(kind=kind, question=question, answer=answer, contexts=contexts)

    variable_names = [str(item).strip() for item in (prompt_variables or []) if str(item).strip()]
    if not variable_names:
        variable_names = ["question", "answer", "contexts"]
    contexts_text = "\n".join([f"[C{i + 1}] {c}" for i, c in enumerate(contexts or [])]).strip()
    payload: dict[str, Any] = {}
    if "question" in variable_names:
        payload["question"] = str(question or "")
    if "answer" in variable_names:
        payload["answer"] = str(answer or "")
    if "contexts" in variable_names:
        payload["contexts"] = contexts_text
    prompt = PromptTemplate(template=str(prompt_content), input_variables=variable_names)
    return str(prompt.format(**payload))


def coerce_llm_judge_payload(raw: Any) -> dict[str, Any]:
    obj = raw if isinstance(raw, dict) else {}
    score_raw = obj.get("score")
    try:
        score = float(score_raw) if score_raw is not None else None
    except Exception:
        score = None
    if score is not None:
        score = round(min(1.0, max(0.0, float(score))), 4)

    reason = clip_text(obj.get("reason") or obj.get("explanation") or "", max_len=240)

    quotes_raw = obj.get("evidence_quotes") or obj.get("quotes") or obj.get("evidence") or []
    quotes: list[str] = []
    if isinstance(quotes_raw, list):
        for item in quotes_raw:
            text = clip_text(item, max_len=160)
            if not text or text in quotes:
                continue
            quotes.append(text)
            if len(quotes) >= 3:
                break
    elif isinstance(quotes_raw, str) and quotes_raw.strip():
        quotes = [clip_text(quotes_raw, max_len=160)]

    out = {"score": score, "reason": reason, "evidence_quotes": quotes}
    detail_fields = {
        "atomic_facts": {"fact", "status", "verdict", "evidence_quote"},
        "chunk_judgments": {"rank", "is_relevant", "evidence_quote"},
        "citation_checks": {"citation", "claim", "verdict", "evidence_quote"},
    }
    for key, allowed_fields in detail_fields.items():
        items: list[dict[str, Any]] = []
        for item in obj.get(key) if isinstance(obj.get(key), list) else []:
            if not isinstance(item, dict):
                continue
            cleaned: dict[str, Any] = {}
            for field in allowed_fields:
                value = item.get(field)
                if isinstance(value, (bool, int, float)) and not isinstance(value, bool):
                    cleaned[field] = value
                elif isinstance(value, bool):
                    cleaned[field] = value
                elif isinstance(value, str) and value.strip():
                    cleaned[field] = clip_text(value, max_len=500)
            if cleaned:
                items.append(cleaned)
            if len(items) >= 100:
                break
        if items:
            out[key] = items
    return out


def _invoke_llm_judge_once(
    *,
    llm: Any,
    kind: str,
    question: str,
    answer: str,
    contexts: list[str],
    prompt_content: str | None = None,
    prompt_variables: list[str] | None = None,
) -> dict[str, Any]:
    prompt = render_llm_judge_prompt(
        kind=kind,
        question=question,
        answer=answer,
        contexts=contexts,
        prompt_content=prompt_content,
        prompt_variables=prompt_variables,
    )
    content = ""
    err: str | None = None
    try:
        response = llm.invoke(prompt)
        content = str(getattr(response, "content", None) or response or "")
    except Exception as exc:  # noqa: BLE001
        err = f"invoke_error:{type(exc).__name__}:{str(exc)[:120]}"

    obj, meta = parse_json_from_text(content, expected="object")
    out = coerce_llm_judge_payload(obj)
    out["ok"] = bool(meta.get("ok"))
    out["method"] = meta.get("method")
    out["error"] = err or meta.get("error")
    return out


def _score_values(rows: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        score = row.get("score") if isinstance(row, dict) else None
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            values.append(float(score))
    return values


def _median_score(rows: list[dict[str, Any]]) -> float | None:
    values = _score_values(rows)
    if not values:
        return None
    return round(float(median(values)), 4)


def _mean_abs_deviation(values: list[float], center: float | None) -> float | None:
    if center is None or not values:
        return None
    return round(sum(abs(float(value) - float(center)) for value in values) / float(len(values)), 4)


def _pick_representative(rows: list[dict[str, Any]], target_score: float | None) -> dict[str, Any]:
    if not rows:
        return {}
    if target_score is None:
        return dict(rows[0])

    best_row = rows[0]
    best_distance = float("inf")
    for row in rows:
        score = row.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            continue
        distance = abs(float(score) - float(target_score))
        if distance < best_distance:
            best_row = row
            best_distance = distance
    return dict(best_row)


def run_llm_judge(
    *,
    llm: Any,
    kind: str,
    question: str,
    answer: str,
    contexts: list[str],
    prompt_content: str | None = None,
    prompt_variables: list[str] | None = None,
    prompt_meta: dict[str, Any] | None = None,
    self_consistency_n: int = 3,
    position_bias_enabled: bool = True,
) -> dict[str, Any]:
    sample_count = max(1, int(self_consistency_n or 1))
    primary_samples = [
        _invoke_llm_judge_once(
            llm=llm,
            kind=kind,
            question=question,
            answer=answer,
            contexts=contexts,
            prompt_content=prompt_content,
            prompt_variables=prompt_variables,
        )
        for _ in range(sample_count)
    ]
    primary_scores = _score_values(primary_samples)
    primary_median = _median_score(primary_samples)
    representative = _pick_representative(primary_samples, primary_median)

    reversed_result: dict[str, Any] | None = None
    reversed_score: float | None = None
    if bool(position_bias_enabled) and len(contexts or []) > 1:
        reversed_result = _invoke_llm_judge_once(
            llm=llm,
            kind=kind,
            question=question,
            answer=answer,
            contexts=list(reversed(contexts)),
            prompt_content=prompt_content,
            prompt_variables=prompt_variables,
        )
        score = reversed_result.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            reversed_score = round(float(score), 4)

    final_candidates = [value for value in (primary_median, reversed_score) if value is not None]
    final_score = round(float(median(final_candidates)), 4) if final_candidates else primary_median

    out = dict(representative)
    out["score"] = final_score
    out["score_forward_median"] = primary_median
    out["self_consistency"] = {
        "n": sample_count,
        "median_score": primary_median,
        "score_mad": _mean_abs_deviation(primary_scores, primary_median),
        "valid_samples": int(len(primary_scores)),
        "samples": [
            {
                "score": row.get("score"),
                "reason": row.get("reason"),
                "ok": bool(row.get("ok")),
                "error": row.get("error"),
            }
            for row in primary_samples[:5]
        ],
    }
    out["position_bias"] = {
        "enabled": bool(position_bias_enabled and len(contexts or []) > 1),
        "forward_median_score": primary_median,
        "reversed_score": reversed_score,
        "delta": (
            round(abs(float(primary_median) - float(reversed_score)), 4)
            if primary_median is not None and reversed_score is not None
            else None
        ),
    }
    if isinstance(reversed_result, dict):
        out["position_bias"]["reversed_reason"] = reversed_result.get("reason")
        out["position_bias"]["reversed_ok"] = bool(reversed_result.get("ok"))
        out["position_bias"]["reversed_error"] = reversed_result.get("error")
    out["score_basis"] = "self_consistency_median"
    if out["position_bias"].get("enabled"):
        out["score_basis"] = "self_consistency_median_position_debiased"
    if isinstance(prompt_meta, dict) and prompt_meta:
        out.update(prompt_meta)
    return out


def attach_llm_judge_to_eval_items(
    *,
    eval_items: list[dict[str, Any]],
    llm: Any,
    db: Any | None = None,
    tenant_id: UUID | None = None,
    judge_prompt_template_id: UUID | None = None,
    judge_prompt_template_key: str | None = None,
    judge_prompt_ab_experiment_key: str | None = None,
    judge_ab_user_key: str | None = None,
    self_consistency_n: int = 3,
    position_bias_enabled: bool = True,
) -> dict[str, Any]:
    model_used = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    generation_prompt_content: str | None = None
    generation_prompt_variables: list[str] | None = None
    generation_prompt_version: int | None = None
    generation_prompt_meta: dict[str, Any] = {}

    if db is not None and tenant_id is not None and (
        judge_prompt_template_id
        or (judge_prompt_template_key or "").strip()
        or (judge_prompt_ab_experiment_key or "").strip()
    ):
        try:
            selected_generation_template = resolve_prompt_template(
                db=db,
                tenant_id=tenant_id,
                prompt_template_id=judge_prompt_template_id,
                template_key=judge_prompt_template_key,
                ab_experiment_key=judge_prompt_ab_experiment_key,
                ab_user_key=judge_ab_user_key,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to resolve llm judge prompt template: %s", exc)
            selected_generation_template = None
        if selected_generation_template is not None:
            generation_prompt_content = str(getattr(selected_generation_template, "content", "") or "").strip() or None
            generation_prompt_variables = list(getattr(selected_generation_template, "variables", None) or [])
            generation_prompt_version = int(getattr(selected_generation_template, "version", 0) or 0) or None
            generation_prompt_meta = {
                "prompt_template_id": str(getattr(selected_generation_template, "id", "") or "") or None,
                "prompt_template_key": str(getattr(selected_generation_template, "template_key", "") or "").strip() or None,
                "prompt_ab_experiment_key": str(getattr(selected_generation_template, "ab_experiment_key", "") or "").strip()
                or None,
                "prompt_ab_variant": str(getattr(selected_generation_template, "ab_variant", "") or "").strip() or None,
                "prompt_template_version": generation_prompt_version,
            }

    judge_version = llm_judge_version_hash(
        model=llm,
        generation_prompt_content=generation_prompt_content,
        generation_prompt_variables=generation_prompt_variables,
        generation_prompt_version=generation_prompt_version,
        self_consistency_n=self_consistency_n,
        position_bias_enabled=position_bias_enabled,
    )

    ret_scores: list[float] = []
    gen_scores: list[float] = []
    overall_scores: list[float] = []

    def _run() -> None:
        for item in eval_items:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or "")
            answer = str(item.get("response") or "")
            contexts = clip_contexts_for_judge(item.get("retrieved_contexts"), max_contexts=6, max_chars=900)
            if not question.strip():
                continue

            retrieval = run_llm_judge(
                llm=llm,
                kind="retrieval",
                question=question,
                answer="",
                contexts=contexts,
                self_consistency_n=self_consistency_n,
                position_bias_enabled=position_bias_enabled,
            )
            generation = run_llm_judge(
                llm=llm,
                kind="generation",
                question=question,
                answer=answer,
                contexts=contexts,
                prompt_content=generation_prompt_content,
                prompt_variables=generation_prompt_variables,
                prompt_meta=generation_prompt_meta,
                self_consistency_n=self_consistency_n,
                position_bias_enabled=position_bias_enabled,
            )

            scores_for_overall: list[float] = []
            retrieval_score = retrieval.get("score")
            generation_score = generation.get("score")
            if isinstance(retrieval_score, (int, float)) and not isinstance(retrieval_score, bool):
                ret_scores.append(float(retrieval_score))
                scores_for_overall.append(float(retrieval_score))
            if isinstance(generation_score, (int, float)) and not isinstance(generation_score, bool):
                gen_scores.append(float(generation_score))
                scores_for_overall.append(float(generation_score))
            overall = round(sum(scores_for_overall) / float(len(scores_for_overall)), 4) if scores_for_overall else None
            if overall is not None:
                overall_scores.append(float(overall))

            meta = item.get("item_meta") if isinstance(item.get("item_meta"), dict) else {}
            meta["llm_judge"] = {
                "enabled": True,
                "model_used": model_used,
                "version_hash": judge_version,
                "self_consistency_n": max(1, int(self_consistency_n or 1)),
                "position_bias_enabled": bool(position_bias_enabled),
                "retrieval": retrieval,
                "generation": generation,
                "overall_score": overall,
            }
            item["item_meta"] = meta

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_cost: float | None = None
    get_openai_callback = None
    try:
        from langchain_community.callbacks.manager import get_openai_callback as _get_openai_callback  # type: ignore

        get_openai_callback = _get_openai_callback
    except Exception:
        get_openai_callback = None

    if get_openai_callback is not None:
        with get_openai_callback() as callback:
            _run()
        prompt_tokens = int(getattr(callback, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(callback, "completion_tokens", 0) or 0)
        total_cost = float(getattr(callback, "total_cost", 0.0) or 0.0)
    else:
        _run()

    def _mean(values: list[float]) -> float | None:
        return round(sum(values) / float(len(values)), 4) if values else None

    return {
        "llm_judge_model_used": str(model_used or "") or None,
        "llm_judge_version_hash": judge_version,
        "llm_judge_items": int(len(overall_scores)),
        "llm_judge_retrieval_avg": _mean(ret_scores),
        "llm_judge_generation_avg": _mean(gen_scores),
        "llm_judge_overall_avg": _mean(overall_scores),
        "llm_judge_prompt_template_id": generation_prompt_meta.get("prompt_template_id"),
        "llm_judge_prompt_template_key": generation_prompt_meta.get("prompt_template_key"),
        "llm_judge_prompt_ab_experiment_key": generation_prompt_meta.get("prompt_ab_experiment_key"),
        "llm_judge_prompt_ab_variant": generation_prompt_meta.get("prompt_ab_variant"),
        "llm_judge_prompt_template_version": generation_prompt_meta.get("prompt_template_version"),
        "llm_judge_self_consistency_n": max(1, int(self_consistency_n or 1)),
        "llm_judge_position_bias_enabled": bool(position_bias_enabled),
        "llm_judge_tokens_input": prompt_tokens,
        "llm_judge_tokens_output": completion_tokens,
        "llm_judge_estimated_cost_usd": (round(float(total_cost), 6) if total_cost is not None else None),
    }


__all__ = [
    "attach_llm_judge_to_eval_items",
    "clip_contexts_for_judge",
    "clip_text",
    "coerce_llm_judge_payload",
    "default_llm_judge_prompt",
    "llm_judge_version_hash",
    "render_llm_judge_prompt",
    "run_llm_judge",
]
