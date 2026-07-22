#!/usr/bin/env python3
"""Build human-like Changzhou mixed RAG evaluation cases.

This script works on an existing deterministic mixed-case pool and produces a
human-query-oriented subset for demos and regression comparisons. It keeps the
evidence clauses unchanged; only the user-facing question/query text and case
sampling mix are adjusted.
"""


import argparse
import copy
import hashlib
import json
import math
import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any

CASES_SCHEMA = "mimirq.mixed_rag_eval_cases.v1"
CASE_GENERATION = "human_mixed_v1"
QA_LIKE_SECTIONS = (
    "03常州市常见问题",
    "04专题常见问答",
    "05业务部门常见问题",
    "06各区常见问题",
)
MECHANICAL_PHRASES = ("请合并回答", "同时告诉我", "请同时说明")
SERVICE_TITLE_RE = re.compile(r"事项名称[:：]\s*(?P<title>[^，。\n]+)")
QUOTED_TITLE_RE = re.compile(r"[“「](?P<title>[^”」]{2,120})[”」]")
FIELD_RE = re.compile(r"^(?P<name>[\u4e00-\u9fffA-Za-z0-9（）()·、/\-]{2,32})[：:](?P<value>.*)$")
ITEM_SEPARATOR = "==##########=="
DIMENSION_PROFILES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "办理材料+办理地点+收费情况",
        ("办理材料", "办理地点", "收费情况"),
        (
            "我准备办「{title}」，要带哪些材料、去哪儿办，费用这块也帮我确认一下。",
            "办「{title}」前我想先问清楚：材料清单、办理地点和收费情况分别是什么？",
        ),
    ),
    (
        "受理条件+承诺办结时限+咨询方式",
        ("受理条件", "承诺办结时限", "咨询方式"),
        (
            "「{title}」我能不能办？受理条件、承诺办结时间和咨询电话帮我看下。",
            "我想了解「{title}」的办理门槛、多久能办完，以及有问题打哪个电话。",
        ),
    ),
    (
        "办理形式+在线办理地址+办理流程",
        ("办理形式", "在线办理地址", "办理流程"),
        (
            "「{title}」能不能网上办？如果可以，入口在哪，办理流程怎么走？",
            "我想办「{title}」，先确认办理形式、线上入口和整体流程。",
        ),
    ),
    (
        "办理时间+办理地点+监督投诉方式",
        ("办理时间", "办理地点", "监督投诉方式"),
        (
            "我去办「{title}」的话，窗口什么时候开、地址在哪，投诉监督电话也给我一下。",
            "「{title}」线下办理前，我想确认办公时间、办理地点和监督投诉方式。",
        ),
    ),
    (
        "办件类型+法定办结时限+承诺办结时限",
        ("办件类型", "法定办结时限", "承诺办结时限"),
        (
            "「{title}」属于什么办件类型？法定时限和承诺时限分别多久？",
            "办理「{title}」大概多久有结果，办件类型、法定和承诺时限帮我区分一下。",
        ),
    ),
    (
        "行使层级+办理形式+办理地点",
        ("行使层级", "办理形式", "办理地点"),
        (
            "「{title}」这个事项是哪一级办理，支持什么办理形式，具体地点在哪里？",
            "我想确认「{title}」归哪个层级办、能不能网办或窗口办，以及去哪里办。",
        ),
    ),
    (
        "受理条件+办理材料+办理流程",
        ("受理条件", "办理材料", "办理流程"),
        (
            "办「{title}」前，我需要确认自己是否符合条件、要交哪些材料、流程怎么走。",
            "「{title}」从资格条件到材料再到办理步骤，帮我按顺序梳理一下。",
        ),
    ),
    (
        "在线办理地址+咨询方式+监督投诉方式",
        ("在线办理地址", "咨询方式", "监督投诉方式"),
        (
            "「{title}」如果线上办，入口在哪里？咨询电话和监督投诉方式也给我。",
            "我想网上办理「{title}」，顺便确认咨询方式和投诉监督渠道。",
        ),
    ),
)
DYNAMIC_DIMENSION_FIELDS = (
    "行使层级",
    "办理形式",
    "办理地点",
    "办理时间",
    "受理条件",
    "办件类型",
    "法定办结时限",
    "承诺办结时限",
    "收费情况",
    "咨询方式",
    "监督投诉方式",
    "办理材料",
    "精细化材料提醒",
    "办理流程",
    "在线办理地址",
)
FIELD_PHRASES = {
    "行使层级": "归哪个层级办理",
    "办理形式": "支持哪些办理方式",
    "办理地点": "到哪里办",
    "办理时间": "什么时间能办",
    "受理条件": "要满足什么条件",
    "办件类型": "属于什么办件类型",
    "法定办结时限": "法定多久办结",
    "承诺办结时限": "承诺多久办结",
    "收费情况": "是否收费",
    "咨询方式": "咨询电话或渠道",
    "监督投诉方式": "监督投诉方式",
    "办理材料": "要准备哪些材料",
    "精细化材料提醒": "材料有什么特别提醒",
    "办理流程": "流程怎么走",
    "在线办理地址": "线上入口在哪里",
}
ONE_THING_EVIDENCE_LABELS = {
    "涉及事项": "涉及事项：",
    "申请材料": "申请材料：",
    "办理渠道": "办理入口：",
    "联系方式": "联系方式",
}
_SOURCE_FIELD_CACHE: dict[tuple[str, str], dict[str, str]] = {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _case_id(case: dict[str, Any]) -> str:
    return _text(case.get("id") or case.get("case_id"))


def _source_section(case: dict[str, Any]) -> str:
    metadata = case.get("metadata") if isinstance(case.get("metadata"), dict) else {}
    extra = case.get("extra") if isinstance(case.get("extra"), dict) else {}
    return _text(case.get("source_section") or metadata.get("knowledge_section") or extra.get("source_section"))


def _case_type(case: dict[str, Any]) -> str:
    return _text(case.get("case_type") or case.get("type"))


def is_qa_like_case(case: dict[str, Any]) -> bool:
    """Return true for FAQ/QA-derived cases, including service rows mined from FAQ files."""

    case_type = _case_type(case).lower()
    source_section = _source_section(case)
    return case_type.startswith("qa_") or case_type == "qa" or source_section in QA_LIKE_SECTIONS


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _subquestion_ids(case: dict[str, Any]) -> list[str]:
    return [_text(item.get("id") or item.get("name")) for item in _list_dicts(case.get("subquestions")) if _text(item.get("id") or item.get("name"))]


def _title_from_evidence(case: dict[str, Any]) -> str:
    for clause in _list_dicts(case.get("evidence_clauses")):
        terms = clause.get("required_terms")
        if not isinstance(terms, list):
            continue
        for term in terms:
            match = SERVICE_TITLE_RE.search(_text(term))
            if match:
                return _clean_title(match.group("title"))
    return ""


def _title_from_question(case: dict[str, Any]) -> str:
    question = _text(case.get("question") or case.get("query"))
    match = QUOTED_TITLE_RE.search(question)
    if match:
        return _clean_title(match.group("title"))
    if question.startswith("关于"):
        head = question.removeprefix("关于").split("，", 1)[0].strip(" ：:")
        if head:
            return _clean_title(head)
    return ""


def _clean_title(value: str) -> str:
    title = _text(value).strip("[]【】")
    for prefix in ("事项名称：", "事项名称:"):
        if title.startswith(prefix):
            title = title[len(prefix) :]
    return title.strip()


def _identity_text(value: str) -> str:
    return re.sub(r"\s+", "", _text(value).translate(str.maketrans({"（": "(", "）": ")"})))


def _case_title(case: dict[str, Any]) -> str:
    for value in (case.get("source_record_title"), case.get("title"), _title_from_evidence(case), _title_from_question(case)):
        title = _clean_title(_text(value))
        if title:
            return title
    return "这个事项"


def _dimension_signature_from_case(case: dict[str, Any]) -> str:
    signature = _text(case.get("dimension_signature"))
    if signature:
        return signature
    fields = _subquestion_ids(case)
    return "+".join(fields)


def _human_dimension_signature(case: dict[str, Any]) -> str:
    fields = _subquestion_ids(case)
    signature = "+".join(fields)
    if _case_type(case) == "one_thing_guide_composite":
        return f"{_case_title(case)}::{signature}"
    return signature


def _parse_fields_from_record_text(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_name = ""
    current_value: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw.strip()
        if not line or line.startswith("==##"):
            continue
        title_match = re.match(r"^\[事项名称[:：](?P<title>.+?)\]\s*$", line)
        if title_match:
            fields["事项名称"] = _clean_title(title_match.group("title"))
            continue
        match = FIELD_RE.match(line)
        if match:
            if current_name:
                fields[current_name] = "\n".join(current_value).strip()
            current_name = match.group("name").strip()
            current_value = [match.group("value").strip()]
            continue
        if current_name:
            current_value.append(line)
    if current_name:
        fields[current_name] = "\n".join(current_value).strip()
    return {key: value for key, value in fields.items() if _text(value)}


def _fields_from_source_file(source_file: str, title: str) -> dict[str, str]:
    source = _text(source_file)
    normalized_title = _identity_text(title)
    if not source or not normalized_title:
        return {}
    cache_key = (source, normalized_title)
    if cache_key in _SOURCE_FIELD_CACHE:
        return dict(_SOURCE_FIELD_CACHE[cache_key])
    path = Path(source)
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    for block in text.split(ITEM_SEPARATOR):
        if normalized_title not in _identity_text(block):
            continue
        fields = _parse_fields_from_record_text(block)
        if _identity_text(fields.get("事项名称", "")) == normalized_title:
            _SOURCE_FIELD_CACHE[cache_key] = fields
            return dict(fields)
    return {}


def _fields_from_evidence(case: dict[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    title = _case_title(case)
    if title:
        fields["事项名称"] = title
    for clause in _list_dicts(case.get("evidence_clauses")):
        terms = [_text(term) for term in clause.get("required_terms") or []]
        for index, term in enumerate(terms):
            label = term.rstrip("：:")
            if term.endswith(("：", ":")) and index + 1 < len(terms):
                fields.setdefault(label, terms[index + 1])
    return {key: value for key, value in fields.items() if _text(value)}


def _record_fields(case: dict[str, Any]) -> dict[str, str]:
    explicit = case.get("source_record_fields") if isinstance(case.get("source_record_fields"), dict) else {}
    fields = {_text(key): _text(value) for key, value in explicit.items() if _text(key) and _text(value)}
    if not fields:
        fields = _fields_from_source_file(_text(case.get("source_file")), _case_title(case))
    if not fields:
        fields = _fields_from_evidence(case)
    fields.setdefault("事项名称", _case_title(case))
    return fields


def _available_dimension_profiles(case: dict[str, Any]) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    if _case_type(case) != "service_item_composite":
        return []
    fields = _record_fields(case)
    dynamic_profiles = [_make_dynamic_profile(names) for names in combinations(DYNAMIC_DIMENSION_FIELDS, 3)]
    out: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    seen_dimension_sets: set[frozenset[str]] = set()
    for profile in (*DIMENSION_PROFILES, *dynamic_profiles):
        signature, names, _ = profile
        dimension_set = frozenset(names)
        if dimension_set in seen_dimension_sets:
            continue
        if all(_text(fields.get(name)) for name in names):
            seen_dimension_sets.add(dimension_set)
            out.append(profile)
    return out


def _make_dynamic_profile(names: tuple[str, ...]) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    signature = "+".join(names)
    phrase = "、".join(FIELD_PHRASES.get(name, name) for name in names)
    return (
        signature,
        names,
        (
            f"我想了解「{{title}}」，{phrase}这几块帮我一起核一下。",
            f"办理「{{title}}」前，{phrase}分别是什么？",
        ),
    )


def _evidence_value(value: str) -> str:
    text = re.sub(r"\s+", " ", _text(value))
    return text[:120].strip()


def _dimension_id(signature: str) -> str:
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:8]


def _build_dimension_case(
    case: dict[str, Any],
    profile: tuple[str, tuple[str, ...], tuple[str, ...]],
    *,
    variant_index: int = 0,
) -> dict[str, Any]:
    signature, names, templates = profile
    fields = _record_fields(case)
    title = _clean_title(fields.get("事项名称") or _case_title(case))
    out = copy.deepcopy(case)
    source_id = _case_id(case)
    if variant_index > 0:
        out["id"] = f"{source_id}-dim-{_dimension_id(signature)}"
        out["case_variant_of"] = source_id
        out["case_variant_index"] = variant_index
        out["case_variant_reason"] = "additional_distinct_dimension_profile"
    out["dimension_signature"] = signature
    out["dimension_fields"] = list(names)
    out["case_generation"] = CASE_GENERATION
    out["qa_like_source"] = is_qa_like_case(out)
    question = templates[_template_index(case, variant_index) % len(templates)].format(title=title)
    out["question"] = question
    out["query"] = question
    out["subquestions"] = [{"id": name, "required_clause_ids": [f"{name}-{index}"]} for index, name in enumerate(names, 1)]
    out["evidence_clauses"] = [
        {
            "id": f"{name}-{index}",
            "required_terms": [f"事项名称：{title}", f"{name}：", _evidence_value(fields[name])],
            "match_scope": "record",
        }
        for index, name in enumerate(names, 1)
    ]
    return out


def _template_index(case: dict[str, Any], variant_index: int) -> int:
    # Stable across runs while still varying repeated title variants.
    seed = sum(ord(char) for char in _case_id(case)) + max(0, int(variant_index))
    return seed


def _pick(templates: tuple[str, ...], case: dict[str, Any], variant_index: int) -> str:
    return templates[_template_index(case, variant_index) % len(templates)]


def _has_all(fields: set[str], *wanted: str) -> bool:
    return all(field in fields for field in wanted)


def _human_question(case: dict[str, Any], *, variant_index: int = 0) -> str:
    title = _case_title(case)
    field_names = _subquestion_ids(case)
    fields = set(field_names)
    field_text = "、".join(field_names[:3]) if field_names else "关键信息"
    case_type = _case_type(case)

    if case_type == "one_thing_guide_composite":
        field_text = "、".join(field_names) if field_names else "关键信息"
        templates = (
            "我想走「{title}」，先帮我梳理{field_text}。",
            "「{title}」申请前，{field_text}分别是什么？",
            "准备办「{title}」，我需要先了解{field_text}。",
        )
    elif is_qa_like_case(case) and case_type.startswith("qa"):
        templates = (
            "我想问下「{title}」这件事，办理地点、周期和费用/注意事项能一起说说吗？",
            "关于「{title}」，实际去办前我想确认地点、时限，还有收费或注意事项。",
            "「{title}」具体怎么办比较清楚？地点、多久办完、费用这些帮我梳理一下。",
        )
    elif _has_all(fields, "办理材料", "办理地点", "收费情况"):
        templates = (
            "我准备办「{title}」，要带哪些材料、去哪儿办，费用这块也帮我确认一下。",
            "办「{title}」前我想先问清楚：材料清单、办理地点和收费情况分别是什么？",
            "「{title}」这个事项如果现在去办，材料、窗口地址和是否收费帮我一次说清楚。",
            "我想办理「{title}」，先帮我核一下需要准备什么、到哪里办理、要不要收费。",
        )
    elif _has_all(fields, "受理条件", "承诺办结时限", "咨询方式"):
        templates = (
            "「{title}」我能不能办？受理条件、承诺办结时间和咨询电话帮我看下。",
            "我想了解「{title}」的办理门槛、多久能办完，以及有问题打哪个电话。",
            "办「{title}」前先确认一下受理条件、承诺时限和咨询方式。",
        )
    else:
        templates = (
            "我想了解「{title}」，{field_text}这些信息能帮我一起看下吗？",
            "「{title}」办理前我需要确认{field_text}，麻烦按实际材料说。",
            "关于「{title}」，我主要想知道{field_text}，请按检索到的依据回答。",
        )
        return _pick(templates, case, variant_index).format(title=title, field_text=field_text)

    return _pick(templates, case, variant_index).format(title=title, field_text=field_text)


def _normalize_one_thing_case(case: dict[str, Any]) -> None:
    if _case_type(case) != "one_thing_guide_composite":
        return
    title = _case_title(case)
    fields = _subquestion_ids(case)
    subquestions: list[dict[str, Any]] = []
    clauses: list[dict[str, Any]] = []
    for index, field in enumerate(fields, 1):
        label = ONE_THING_EVIDENCE_LABELS.get(field, f"{field}：")
        clause_id = f"{field}-{index}"
        subquestions.append({"id": field, "required_clause_ids": [clause_id]})
        clauses.append(
            {
                "id": clause_id,
                "required_terms": [f"一件事：{title}", label],
                "match_scope": "record",
            }
        )
    if subquestions and clauses:
        case["subquestions"] = subquestions
        case["evidence_clauses"] = clauses


def humanize_case(case: dict[str, Any], *, variant_index: int = 0) -> dict[str, Any]:
    out = copy.deepcopy(case)
    _normalize_one_thing_case(out)
    question = _human_question(out, variant_index=variant_index)
    out["question"] = question
    out["query"] = question
    out["case_generation"] = CASE_GENERATION
    out["qa_like_source"] = is_qa_like_case(out)
    out["dimension_signature"] = _human_dimension_signature(out)
    out["dimension_fields"] = _subquestion_ids(out)
    return out


def _dedupe_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in cases:
        case_id = _case_id(case)
        if not case_id or case_id in seen:
            continue
        seen.add(case_id)
        out.append(dict(case))
    return out


def _variant_case(case: dict[str, Any], *, variant_index: int) -> dict[str, Any]:
    source_id = _case_id(case)
    profiles = _available_dimension_profiles(case)
    if profiles:
        out = _build_dimension_case(case, profiles[variant_index % len(profiles)], variant_index=variant_index)
        return out
    out = humanize_case(case, variant_index=variant_index)
    out["id"] = f"{source_id}-human-v{variant_index}"
    out["case_variant_of"] = source_id
    out["case_variant_index"] = variant_index
    out["case_variant_reason"] = "filled_target_total_after_qa_cap"
    return out


def _primary_case(case: dict[str, Any], *, case_index: int, used_global_dimensions: set[str] | None = None) -> dict[str, Any]:
    profiles = _available_dimension_profiles(case)
    if not profiles:
        return humanize_case(case)
    used = used_global_dimensions or set()
    for profile in profiles:
        if profile[0] not in used:
            return _build_dimension_case(case, profile)
    return _build_dimension_case(case, profiles[case_index % len(profiles)])


def build_human_mixed_cases(
    cases: list[dict[str, Any]],
    *,
    total: int = 100,
    max_qa_ratio: float = 0.10,
) -> list[dict[str, Any]]:
    if total <= 0:
        return []
    deduped = _dedupe_cases(cases)
    qa_cap = max(0, math.floor(float(total) * max(0.0, min(1.0, float(max_qa_ratio))) + 1e-9))
    preferred = [case for case in deduped if not is_qa_like_case(case)]
    dimension_preferred = [case for case in preferred if _available_dimension_profiles(case)]
    fallback_preferred = [case for case in preferred if not _available_dimension_profiles(case)]
    qa_like = [case for case in deduped if is_qa_like_case(case)]

    selected: list[dict[str, Any]] = []
    used_global_dimensions: set[str] = set()
    used_dimensions_by_source: dict[str, set[str]] = {}

    def add_dimension_case(case: dict[str, Any], *, variant_index: int) -> bool:
        source_id = _case_id(case)
        used_dimensions = used_dimensions_by_source.setdefault(source_id, set())
        profiles = [profile for profile in _available_dimension_profiles(case) if profile[0] not in used_dimensions]
        if not profiles:
            return False
        globally_new = [profile for profile in profiles if profile[0] not in used_global_dimensions]
        if not globally_new:
            return False
        profile = globally_new[0]
        next_case = _build_dimension_case(case, profile, variant_index=variant_index)
        used_dimensions.add(_dimension_signature_from_case(next_case))
        used_global_dimensions.add(_dimension_signature_from_case(next_case))
        selected.append(next_case)
        return True

    for case in dimension_preferred:
        if len(selected) >= total:
            break
        add_dimension_case(case, variant_index=0)

    remaining = total - len(selected)
    if remaining > 0:
        for index, case in enumerate(fallback_preferred[:remaining]):
            next_case = _primary_case(case, case_index=index, used_global_dimensions=used_global_dimensions)
            used_global_dimensions.add(_dimension_signature_from_case(next_case))
            selected.append(next_case)

    variant_index = 1
    while len(selected) < total and dimension_preferred:
        added_this_round = False
        for case in dimension_preferred:
            if len(selected) >= total:
                break
            added_this_round = add_dimension_case(case, variant_index=variant_index) or added_this_round
        if not added_this_round:
            break
        variant_index += 1

    remaining = total - len(selected)
    if remaining > 0 and qa_cap > 0:
        for index, case in enumerate(qa_like[: min(remaining, qa_cap)]):
            next_case = _primary_case(case, case_index=index, used_global_dimensions=used_global_dimensions)
            used_global_dimensions.add(_dimension_signature_from_case(next_case))
            selected.append(next_case)
    return selected[:total]


def load_cases(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        cases = payload.get("cases")
        if not isinstance(cases, list):
            raise ValueError("cases object must contain cases[]")
        return dict(payload), [dict(item) for item in cases if isinstance(item, dict)]
    if isinstance(payload, list):
        return {"schema": CASES_SCHEMA}, [dict(item) for item in payload if isinstance(item, dict)]
    raise ValueError("cases file must be a list or an object with cases[]")


def _summary(cases: list[dict[str, Any]], *, max_qa_ratio: float) -> dict[str, Any]:
    return {
        "total": len(cases),
        "max_qa_ratio": max_qa_ratio,
        "qa_like_cases": sum(1 for case in cases if is_qa_like_case(case)),
        "variant_cases": sum(1 for case in cases if _text(case.get("case_variant_of"))),
        "case_types": dict(Counter(_case_type(case) for case in cases)),
        "source_sections": dict(Counter(_source_section(case) for case in cases)),
        "dimension_signatures": dict(Counter(_dimension_signature_from_case(case) for case in cases)),
    }


def build_payload(
    source_payload: dict[str, Any],
    cases: list[dict[str, Any]],
    *,
    total: int,
    max_qa_ratio: float,
) -> dict[str, Any]:
    selected = build_human_mixed_cases(cases, total=total, max_qa_ratio=max_qa_ratio)
    payload = dict(source_payload)
    payload["schema"] = CASES_SCHEMA
    payload["description"] = (
        "Human-like complex Changzhou government-service RAG cases prioritizing raw non-QA corpus files."
    )
    payload["cases"] = selected
    payload["generation_policy"] = {
        "name": CASE_GENERATION,
        "question_style": "human_like_composite_queries",
        "source_priority": "non_qa_raw_cases_before_dimension_variants",
        "qa_like_sections": list(QA_LIKE_SECTIONS),
        "mechanical_phrases_removed": list(MECHANICAL_PHRASES),
        "summary": _summary(selected, max_qa_ratio=max_qa_ratio),
    }
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build human-like Changzhou mixed RAG eval cases.")
    parser.add_argument("--cases", required=True, help="Source cases JSON: list or mimirq.mixed_rag_eval_cases.v1 object.")
    parser.add_argument("--out", required=True, help="Output cases JSON path.")
    parser.add_argument("--total", type=int, default=100, help="Target number of output cases.")
    parser.add_argument("--max-qa-ratio", type=float, default=0.10, help="Maximum FAQ/QA-derived case ratio.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    source_payload, cases = load_cases(args.cases)
    payload = build_payload(source_payload, cases, total=args.total, max_qa_ratio=args.max_qa_ratio)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = payload["generation_policy"]["summary"]
    sys.stdout.write(
        "built {total} cases; qa_like={qa_like_cases}; variants={variant_cases}".format(
            total=summary["total"],
            qa_like_cases=summary["qa_like_cases"],
            variant_cases=summary["variant_cases"],
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
