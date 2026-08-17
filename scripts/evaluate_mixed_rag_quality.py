#!/usr/bin/env python3
"""Deterministic evaluator for complex mixed RAG questions.

The evaluator intentionally avoids LLM-as-judge scoring. Cases declare
subquestions and evidence clauses, while each system run supplies retrieved
records and optional generated answers. Scores are computed by deterministic
term/metadata matching so reviewers can inspect exactly which evidence was
missed.
"""

import argparse
import itertools
import json
import math
import statistics
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "mimirq.mixed_rag_quality_report.v1"
CASES_SCHEMA = "mimirq.mixed_rag_eval_cases.v1"
RUN_SCHEMA = "mimirq.mixed_rag_eval_run.v1"
QUALITY_GATE_EXIT_CODE = 3
_METADATA_VIEW_KEYS = ("_evaluable_metadata", "_display_metadata")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_match_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _text(value)).lower()
    out: list[str] = []
    for char in text:
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category.startswith(("P", "S")):
            continue
        out.append(char)
    return "".join(out)


def _quality_point_value(point: str) -> str:
    text = _text(point)
    colon_positions = [index for index in (text.find("："), text.find(":")) if index >= 0]
    if not colon_positions:
        return ""
    return text[min(colon_positions) + 1 :].strip()


def _term_in_text(term: Any, text: str) -> bool:
    normalized_term = _normalize_match_text(term)
    normalized_text = _normalize_match_text(text)
    if normalized_term and normalized_term in normalized_text:
        return True
    value = _normalize_match_text(_quality_point_value(_text(term)))
    return len(value) >= 2 and value in normalized_text


def _term_or_alias_in_text(term: Any, text: str, aliases: dict[str, list[str]] | None = None) -> bool:
    if _term_in_text(term, text):
        return True
    alias_terms = (aliases or {}).get(_text(term)) or []
    return any(_term_in_text(alias, text) for alias in alias_terms)


def _all_terms_match(terms: list[str], text: str, aliases: dict[str, list[str]] | None = None) -> bool:
    return all(_term_or_alias_in_text(term, text, aliases) for term in terms)


def _dedupe_texts(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _list_texts(value: Any) -> list[str]:
    if isinstance(value, list | tuple | set):
        return _dedupe_texts(list(value))
    text = _text(value)
    return [text] if text else []


def _string_list_map(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, list[str]] = {}
    for raw_key, raw_values in value.items():
        key = _text(raw_key)
        values = _list_texts(raw_values)
        if key and values:
            out[key] = values
    return out


def _required_terms(raw: dict[str, Any]) -> list[str]:
    for key in ("required_terms", "all_terms", "terms", "content_contains", "answer_key_points"):
        values = _list_texts(raw.get(key))
        if values:
            return values
    return []


def _required_clause_ids(raw: dict[str, Any]) -> list[str]:
    for key in ("required_clause_ids", "evidence_clause_ids", "clause_ids"):
        values = _list_texts(raw.get(key))
        if values:
            return values
    return []


def _record_text(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    fields = [
        record.get("title"),
        record.get("content"),
        record.get("text"),
        metadata.get("title"),
        metadata.get("document_name"),
        metadata.get("service_name"),
    ]
    return "\n".join(_text(field) for field in fields if _text(field))


def _records_text(records: list[dict[str, Any]], *, top_k: int | None = None) -> str:
    selected = records if top_k is None else records[: max(0, int(top_k))]
    return "\n".join(_record_text(record) for record in selected)


def _metadata_layers(record_meta: dict[str, Any]) -> list[dict[str, Any]]:
    layers = [record_meta]
    for key in _METADATA_VIEW_KEYS:
        nested = record_meta.get(key)
        if isinstance(nested, dict):
            layers.append(nested)
    return layers


def _metadata_value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, list | tuple | set):
        return any(_metadata_value_matches(actual, item) for item in expected)
    if isinstance(expected, str):
        return _term_in_text(expected, _text(actual))
    return actual == expected


def _metadata_matches(record: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not expected:
        return True
    meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return any(
        all(_metadata_value_matches(layer.get(key), expected_value) for key, expected_value in expected.items())
        for layer in _metadata_layers(meta)
    )


def _case_id(case: dict[str, Any]) -> str:
    return _text(case.get("id") or case.get("case_id"))


def _case_question(case: dict[str, Any]) -> str:
    return _text(case.get("question") or case.get("query"))


def _normalize_clause(raw: Any, index: int) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"id": raw or f"clause-{index}", "required_terms": [raw], "metadata": {}, "match_scope": "record"}
    item = dict(raw) if isinstance(raw, dict) else {}
    clause_id = _text(item.get("id") or item.get("name") or f"clause-{index}")
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "id": clause_id,
        "required_terms": _required_terms(item),
        "metadata": dict(metadata),
        "match_scope": _text(item.get("match_scope") or item.get("scope") or "record").lower(),
    }


def _normalize_subquestion(raw: Any, index: int) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"id": raw or f"subquestion-{index}", "required_terms": [raw], "required_clause_ids": []}
    item = dict(raw) if isinstance(raw, dict) else {}
    sub_id = _text(item.get("id") or item.get("name") or f"subquestion-{index}")
    return {
        "id": sub_id,
        "required_terms": _required_terms(item),
        "required_clause_ids": _required_clause_ids(item),
    }


def _case_clauses(case: dict[str, Any]) -> list[dict[str, Any]]:
    raw = case.get("evidence_clauses")
    if not isinstance(raw, list):
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        raw = expected.get("answer_key_points") if isinstance(expected.get("answer_key_points"), list) else []
    return [_normalize_clause(item, index) for index, item in enumerate(raw or [], 1)]


def _case_subquestions(case: dict[str, Any]) -> list[dict[str, Any]]:
    raw = case.get("subquestions")
    if not isinstance(raw, list):
        raw = []
    return [_normalize_subquestion(item, index) for index, item in enumerate(raw, 1)]


def _case_answer_term_aliases(case: dict[str, Any]) -> dict[str, list[str]]:
    aliases = _string_list_map(case.get("answer_term_aliases"))
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    for key, values in _string_list_map(expected.get("answer_term_aliases")).items():
        aliases.setdefault(key, [])
        aliases[key] = _dedupe_texts([*aliases[key], *values])
    return aliases


def _case_float(case: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(case.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _run_item_id(item: dict[str, Any]) -> str:
    return _text(item.get("case_id") or item.get("id"))


def _answer_text(item: dict[str, Any]) -> str:
    for key in ("answer", "text", "content", "result"):
        text = _text(item.get(key))
        if text:
            return text
    data = item.get("data")
    if isinstance(data, dict):
        outputs = data.get("outputs")
        if isinstance(outputs, dict):
            for key in ("answer", "text", "content", "result", "output"):
                text = _text(outputs.get(key))
                if text:
                    return text
    return ""


def _normalize_record(raw: Any, index: int) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"title": f"record-{index}", "content": raw, "metadata": {}}
    if not isinstance(raw, dict):
        return {"title": f"record-{index}", "content": "", "metadata": {}}
    record = dict(raw)
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    record["metadata"] = dict(metadata)
    return record


def _records_from_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("records", "retrieved_records", "retrieval_records", "contexts"):
        raw = item.get(key)
        if isinstance(raw, list):
            return [_normalize_record(record, index) for index, record in enumerate(raw, 1)]
    return []


def _latency_ms(item: dict[str, Any]) -> float | None:
    for key in ("total_latency_ms", "latency_ms", "elapsed_ms", "duration_ms"):
        if key not in item:
            continue
        try:
            return float(item.get(key))
        except (TypeError, ValueError):
            return None
    return None


def _clause_matches_records(clause: dict[str, Any], records: list[dict[str, Any]]) -> tuple[bool, list[int]]:
    terms = list(clause.get("required_terms") or [])
    if not terms:
        return False, []
    metadata = clause.get("metadata") if isinstance(clause.get("metadata"), dict) else {}
    if clause.get("match_scope") == "aggregate":
        text = _records_text(records)
        if _all_terms_match(terms, text) and all(_metadata_matches(record, metadata) for record in records):
            return True, list(range(1, len(records) + 1))
        return False, []
    matched: list[int] = []
    for index, record in enumerate(records, 1):
        if not _metadata_matches(record, metadata):
            continue
        if _all_terms_match(terms, _record_text(record)):
            matched.append(index)
    return bool(matched), matched


def _clause_matches_answer(clause: dict[str, Any], answer: str, aliases: dict[str, list[str]] | None = None) -> bool:
    terms = list(clause.get("required_terms") or [])
    return bool(terms) and _all_terms_match(terms, answer, aliases)


def _score_subquestion(
    subquestion: dict[str, Any],
    *,
    records_text: str,
    answer: str,
    matched_clause_ids: set[str],
    answer_clause_ids: set[str],
    answer_aliases: dict[str, list[str]],
) -> dict[str, Any]:
    required_terms = list(subquestion.get("required_terms") or [])
    required_clause_ids = set(_list_texts(subquestion.get("required_clause_ids")))
    evidence_terms_ok = _all_terms_match(required_terms, records_text) if required_terms else True
    answer_terms_ok = _all_terms_match(required_terms, answer, answer_aliases) if required_terms else True
    evidence_clauses_ok = required_clause_ids <= matched_clause_ids if required_clause_ids else True
    answer_clauses_ok = required_clause_ids <= answer_clause_ids if required_clause_ids else True
    return {
        "id": _text(subquestion.get("id")),
        "evidence_matched": evidence_terms_ok and evidence_clauses_ok,
        "answer_matched": bool(answer) and answer_terms_ok and answer_clauses_ok,
    }


def _record_supports_any(
    record: dict[str, Any], clauses: list[dict[str, Any]], subquestions: list[dict[str, Any]]
) -> bool:
    text = _record_text(record)
    for clause in clauses:
        terms = list(clause.get("required_terms") or [])
        if terms and _metadata_matches(record, clause.get("metadata") or {}) and _all_terms_match(terms, text):
            return True
    for subquestion in subquestions:
        terms = list(subquestion.get("required_terms") or [])
        if terms and _all_terms_match(terms, text):
            return True
    return False


def _ratio(numerator: int | float, denominator: int | float, *, empty: float) -> float:
    denominator_value = float(denominator)
    if denominator_value <= 0.0:
        return float(empty)
    return float(numerator) / denominator_value


def _round_float(value: float | None) -> float | None:
    if value is None:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return round(float(value), 6)


def evaluate_item(case: dict[str, Any], run: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    records = _records_from_item(item)
    answer = _answer_text(item)
    clauses = _case_clauses(case)
    subquestions = _case_subquestions(case)
    answer_aliases = _case_answer_term_aliases(case)
    records_text = _records_text(records)

    matched_clause_ids: set[str] = set()
    answer_clause_ids: set[str] = set()
    clause_rows: list[dict[str, Any]] = []
    for clause in clauses:
        clause_id = _text(clause.get("id"))
        evidence_matched, record_ranks = _clause_matches_records(clause, records)
        answer_matched = _clause_matches_answer(clause, answer, answer_aliases)
        if evidence_matched:
            matched_clause_ids.add(clause_id)
        if answer_matched:
            answer_clause_ids.add(clause_id)
        clause_rows.append(
            {
                "id": clause_id,
                "evidence_matched": evidence_matched,
                "answer_matched": answer_matched,
                "record_ranks": record_ranks,
            }
        )

    subquestion_rows = [
        _score_subquestion(
            subquestion,
            records_text=records_text,
            answer=answer,
            matched_clause_ids=matched_clause_ids,
            answer_clause_ids=answer_clause_ids,
            answer_aliases=answer_aliases,
        )
        for subquestion in subquestions
    ]
    forbidden_terms = _list_texts(case.get("forbidden_terms"))
    forbidden_hits = [
        term for term in forbidden_terms if _term_in_text(term, records_text) or _term_in_text(term, answer)
    ]
    effective_records = sum(1 for record in records if _record_supports_any(record, clauses, subquestions))
    evaluated_records = len(records)

    evidence_total = len(clauses)
    subquestion_total = len(subquestion_rows)
    evidence_matched = len(matched_clause_ids)
    answer_clause_matched = len(answer_clause_ids)
    subquestion_matched = sum(1 for row in subquestion_rows if row["evidence_matched"])
    answer_subquestion_matched = sum(1 for row in subquestion_rows if row["answer_matched"])
    unsupported_answered_clause_ids = sorted(answer_clause_ids - matched_clause_ids)
    answer_supported_clause_rate = _ratio(
        len(answer_clause_ids & matched_clause_ids),
        len(answer_clause_ids),
        empty=1.0 if not answer else 0.0,
    )
    wrong_evidence_rate = 1.0 - _ratio(effective_records, evaluated_records, empty=0.0)
    evidence_coverage = _ratio(evidence_matched, evidence_total, empty=1.0)
    subquestion_coverage = _ratio(subquestion_matched, subquestion_total, empty=1.0)

    min_evidence = max(0.0, min(1.0, _case_float(case, "min_evidence_coverage", 1.0)))
    min_subquestion = max(0.0, min(1.0, _case_float(case, "min_subquestion_coverage", 1.0)))
    max_wrong = max(0.0, min(1.0, _case_float(case, "max_wrong_evidence_rate", 1.0)))
    passed_retrieval = (
        evidence_coverage >= min_evidence
        and subquestion_coverage >= min_subquestion
        and wrong_evidence_rate <= max_wrong
        and not forbidden_hits
    )
    return {
        "system": _text(run.get("system")),
        "case_id": _case_id(case),
        "question": _case_question(case),
        "records": evaluated_records,
        "latency_ms": _round_float(_latency_ms(item)),
        "evidence_clauses_total": evidence_total,
        "evidence_clauses_matched": evidence_matched,
        "evidence_coverage": _round_float(evidence_coverage),
        "missing_evidence_clause_ids": [row["id"] for row in clause_rows if not row["evidence_matched"]],
        "subquestions_total": subquestion_total,
        "subquestions_matched": subquestion_matched,
        "subquestion_coverage": _round_float(subquestion_coverage),
        "missing_subquestion_ids": [row["id"] for row in subquestion_rows if not row["evidence_matched"]],
        "answer_clause_coverage": _round_float(_ratio(answer_clause_matched, evidence_total, empty=1.0)),
        "answer_subquestion_coverage": _round_float(_ratio(answer_subquestion_matched, subquestion_total, empty=1.0)),
        "answer_supported_clause_rate": _round_float(answer_supported_clause_rate),
        "unsupported_answered_clause_ids": unsupported_answered_clause_ids,
        "effective_records": effective_records,
        "evaluated_records": evaluated_records,
        "wrong_evidence_rate": _round_float(wrong_evidence_rate),
        "forbidden_terms_hit": forbidden_hits,
        "passed_retrieval": passed_retrieval,
        "clause_results": clause_rows,
        "subquestion_results": subquestion_rows,
    }


def _items_by_case(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = run.get("items")
    if not isinstance(items, list):
        items = run.get("answers") if isinstance(run.get("answers"), list) else []
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        case_id = _run_item_id(item)
        if case_id:
            out[case_id] = dict(item)
    return out


def _mean(values: list[float | None], *, empty: float = 0.0) -> float:
    clean = [float(value) for value in values if value is not None]
    return statistics.fmean(clean) if clean else float(empty)


def _summarize_system(system: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    cases = len(items)
    latencies = [item.get("latency_ms") for item in items if item.get("latency_ms") is not None]
    return {
        "system": system,
        "cases": cases,
        "retrieval_pass_rate": _round_float(
            _ratio(sum(1 for item in items if item["passed_retrieval"]), cases, empty=0.0)
        ),
        "mean_evidence_coverage": _round_float(_mean([item.get("evidence_coverage") for item in items])),
        "mean_subquestion_coverage": _round_float(_mean([item.get("subquestion_coverage") for item in items])),
        "mean_answer_clause_coverage": _round_float(_mean([item.get("answer_clause_coverage") for item in items])),
        "mean_answer_subquestion_coverage": _round_float(
            _mean([item.get("answer_subquestion_coverage") for item in items])
        ),
        "mean_answer_supported_clause_rate": _round_float(
            _mean([item.get("answer_supported_clause_rate") for item in items])
        ),
        "mean_wrong_evidence_rate": _round_float(_mean([item.get("wrong_evidence_rate") for item in items])),
        "unsupported_answered_clause_cases": sum(1 for item in items if item["unsupported_answered_clause_ids"]),
        "forbidden_hit_cases": sum(1 for item in items if item["forbidden_terms_hit"]),
        "mean_latency_ms": _round_float(_mean(latencies, empty=0.0)) if latencies else None,
    }


def _leaderboard_key(row: dict[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        float(row.get("mean_evidence_coverage") or 0.0),
        float(row.get("mean_subquestion_coverage") or 0.0),
        float(row.get("mean_answer_supported_clause_rate") or 0.0),
        -float(row.get("mean_wrong_evidence_rate") or 0.0),
        -float(row.get("mean_latency_ms") or 0.0),
    )


def _pairwise(systems: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_system_case = {(item["system"], item["case_id"]): item for item in items}
    out: list[dict[str, Any]] = []
    for left, right in itertools.combinations([row["system"] for row in systems], 2):
        shared_case_ids = sorted(
            {case_id for system, case_id in by_system_case if system == left and (right, case_id) in by_system_case}
        )
        left_wins = right_wins = ties = 0
        deltas: list[dict[str, Any]] = []
        for case_id in shared_case_ids:
            left_item = by_system_case[(left, case_id)]
            right_item = by_system_case[(right, case_id)]
            left_score = (
                float(left_item.get("evidence_coverage") or 0.0),
                float(left_item.get("subquestion_coverage") or 0.0),
            )
            right_score = (
                float(right_item.get("evidence_coverage") or 0.0),
                float(right_item.get("subquestion_coverage") or 0.0),
            )
            if left_score > right_score:
                left_wins += 1
            elif right_score > left_score:
                right_wins += 1
            else:
                ties += 1
            deltas.append(
                {
                    "case_id": case_id,
                    "left_evidence_coverage": left_item.get("evidence_coverage"),
                    "right_evidence_coverage": right_item.get("evidence_coverage"),
                    "left_subquestion_coverage": left_item.get("subquestion_coverage"),
                    "right_subquestion_coverage": right_item.get("subquestion_coverage"),
                }
            )
        out.append(
            {
                "left": left,
                "right": right,
                "shared_cases": len(shared_case_ids),
                "left_wins": left_wins,
                "right_wins": right_wins,
                "ties": ties,
                "case_deltas": deltas,
            }
        )
    return out


def evaluate_mixed_rag_quality(*, cases: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    case_map = {_case_id(case): case for case in cases if _case_id(case)}
    items: list[dict[str, Any]] = []
    for run_index, run in enumerate(runs, 1):
        system = _text(run.get("system")) or f"system-{run_index}"
        effective_run = {**run, "system": system}
        run_items = _items_by_case(effective_run)
        for case_id, case in case_map.items():
            item = run_items.get(case_id)
            if item is None:
                item = {"case_id": case_id, "records": [], "answer": ""}
            items.append(evaluate_item(case, effective_run, item))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item["system"], []).append(item)
    systems = [_summarize_system(system, grouped[system]) for system in sorted(grouped)]
    leaderboard = [
        {"rank": index, **row} for index, row in enumerate(sorted(systems, key=_leaderboard_key, reverse=True), start=1)
    ]
    return {
        "schema": SCHEMA,
        "generated_at": _utc_now_text(),
        "method": {
            "judge": "deterministic_term_and_metadata_matching",
            "llm_judge": False,
            "unit": "case_subquestions_and_evidence_clauses",
        },
        "summary": {"cases": len(case_map), "systems": len(systems), "items": len(items)},
        "systems": systems,
        "leaderboard": leaderboard,
        "pairwise": _pairwise(systems, items),
        "items": items,
    }


def load_cases(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("cases file must be a list or an object with cases[]")
    return [dict(item) for item in cases if isinstance(item, dict)]


def _load_run_arg(value: str) -> dict[str, Any]:
    label = ""
    path_text = value
    if "=" in value:
        label, path_text = value.split("=", 1)
    payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"run file must be a JSON object: {path_text}")
    run = dict(payload)
    if _text(label):
        run["system"] = _text(label)
    elif not _text(run.get("system")):
        run["system"] = Path(path_text).stem
    return run


def _evaluate_gate(report: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    thresholds = {
        "mean_evidence_coverage": args.min_mean_evidence_coverage,
        "mean_subquestion_coverage": args.min_mean_subquestion_coverage,
    }
    maximums = {"mean_wrong_evidence_rate": args.max_mean_wrong_evidence_rate}
    for system in report.get("systems") or []:
        if not isinstance(system, dict):
            continue
        for metric, minimum in thresholds.items():
            if minimum is None:
                continue
            actual = float(system.get(metric) or 0.0)
            checks.append(
                {
                    "system": system.get("system"),
                    "metric": metric,
                    "actual": actual,
                    "minimum": float(minimum),
                    "passed": actual >= float(minimum),
                }
            )
        for metric, maximum in maximums.items():
            if maximum is None:
                continue
            actual = float(system.get(metric) or 0.0)
            checks.append(
                {
                    "system": system.get("system"),
                    "metric": metric,
                    "actual": actual,
                    "maximum": float(maximum),
                    "passed": actual <= float(maximum),
                }
            )
    failed = sum(1 for check in checks if check.get("passed") is not True)
    return {"passed": failed == 0, "failed": failed, "checks": checks}


def build_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Mixed RAG Quality Report",
        "",
        "Scoring method: deterministic term and metadata matching; no LLM judge.",
        "",
        "## Leaderboard",
        "",
        "| System | Cases | Evidence | Subquestions | Answer Support | Wrong Evidence | Mean Latency ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("leaderboard") or []:
        latency = row.get("mean_latency_ms")
        latency_text = "" if latency is None else f"{float(latency):.1f}"
        lines.append(
            "| {system} | {cases} | {evidence:.3f} | {subq:.3f} | {support:.3f} | {wrong:.3f} | {latency} |".format(
                system=row.get("system"),
                cases=int(row.get("cases") or 0),
                evidence=float(row.get("mean_evidence_coverage") or 0.0),
                subq=float(row.get("mean_subquestion_coverage") or 0.0),
                support=float(row.get("mean_answer_supported_clause_rate") or 0.0),
                wrong=float(row.get("mean_wrong_evidence_rate") or 0.0),
                latency=latency_text,
            )
        )
    lines.extend(["", "## Missing Evidence", ""])
    for item in report.get("items") or []:
        if not isinstance(item, dict):
            continue
        missing = item.get("missing_evidence_clause_ids") or []
        unsupported = item.get("unsupported_answered_clause_ids") or []
        if not missing and not unsupported:
            continue
        lines.append(
            "- {system} / {case_id}: missing={missing}; unsupported_answer={unsupported}".format(
                system=item.get("system"),
                case_id=item.get("case_id"),
                missing=",".join(missing) if missing else "-",
                unsupported=",".join(unsupported) if unsupported else "-",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate complex mixed RAG cases using deterministic evidence rubrics."
    )
    parser.add_argument("--cases", required=True, help="Cases JSON: list or mimirq.mixed_rag_eval_cases.v1 object.")
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="Run JSON. Use label=/path/run.json to override system name. Repeat for multiple systems.",
    )
    parser.add_argument("--out", default="", help="Output JSON report path.")
    parser.add_argument("--out-md", default="", help="Optional Markdown report path.")
    parser.add_argument("--min-mean-evidence-coverage", type=float, default=None)
    parser.add_argument("--min-mean-subquestion-coverage", type=float, default=None)
    parser.add_argument("--max-mean-wrong-evidence-rate", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        if not args.run:
            print("--run is required at least once", file=sys.stderr)
            return 2
        report = evaluate_mixed_rag_quality(
            cases=load_cases(str(args.cases)), runs=[_load_run_arg(value) for value in args.run]
        )
        report["gate"] = _evaluate_gate(report, args)
    except Exception as exc:  # noqa: BLE001
        print(f"[mixed-rag-quality] ERR: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.out_md:
        Path(str(args.out_md)).write_text(build_markdown_report(report), encoding="utf-8")
    return 0 if bool(report["gate"]["passed"]) else QUALITY_GATE_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
