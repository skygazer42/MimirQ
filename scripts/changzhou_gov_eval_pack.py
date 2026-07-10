#!/usr/bin/env python3
"""Build a large Changzhou government-service evaluation pack from raw corpus files.

Outputs:
- benchmark cases (same evidence-first shape used by dify_3way_benchmark)
- truth manifest
- regression bundle draft
- optional regression import + retrieval-only run against the local backend
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pandas as pd
from docx import Document as DocxDocument
from sqlalchemy import and_

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.database import SessionLocal
from app.models.document import Document, DocumentChunk
from app.services.regression_case_bundle import REGRESSION_CASE_BUNDLE_SCHEMA_V1

DEFAULT_CORPUS_ROOT = "/path/to/gov-service-knowledge"
DEFAULT_OUT_DIR = "artifacts/changzhou_eval_pack_1000"
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
DEFAULT_USER_ID = "demo"
DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8000/api/v1"
CASES_SCHEMA = "mimirq.changzhou_gov_eval_cases.v1"
TRUTH_SCHEMA = "mimirq.changzhou_gov_eval_truth.v1"
GENERATION_NAME = "changzhou_corpus_eval_pack_v1"
SERVICE_ITEM_SEPARATOR = "==##########=="
SERVICE_TITLE_RE = re.compile(r"^\[事项名称[:：](?P<title>.+?)\]\s*$")
QA_QUESTION_RE = re.compile(r"^问题[:：]\[(?P<question>.+?)\]\s*$")
QA_ANSWER_RE = re.compile(r"^答案[:：](?P<answer>.*)$")
QA_SOURCE_RE = re.compile(r"^来源部门[:：](?P<source>.*)$")
FIELD_RE = re.compile(r"^(?P<name>[\u4e00-\u9fffA-Za-z0-9（）()·、/\-]{2,40})[:：](?P<value>.*)$")
PHONE_RE = re.compile(r"(?:0\d{2,3}-?)?\d{7,8}")
URL_RE = re.compile(r"https?://\S+")
KNOWN_DISTRICTS = (
    "常州市",
    "新北区",
    "经开区",
    "天宁区",
    "钟楼区",
    "武进区",
    "金坛区",
    "溧阳市",
)
FIELD_ALIASES: dict[str, list[str]] = {
    "办理地点": ["办理地址", "办理地点", "地址", "地点", "窗口"],
    "咨询方式": ["咨询电话", "联系电话", "联系方式", "电话", "咨询方式"],
    "收费情况": ["收费", "费用", "是否收费", "免费", "不收费"],
    "办理时间": ["办理时间", "办公时间", "上班时间"],
    "在线办理地址": ["线上入口", "网办入口", "线上办理地址", "网上办理地址"],
    "办理材料": ["材料", "资料", "材料清单", "要带什么"],
}
DIMENSION_PROFILES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "办理材料+办理地点+收费情况",
        ("办理材料", "办理地点", "收费情况"),
        (
            "请问“{title}”这个事项的办理材料、办理地点和收费情况分别是什么？",
            "“{title}”办理时，材料清单、办理地点和收费情况能帮我一次说清楚吗？",
        ),
    ),
    (
        "受理条件+承诺办结时限+咨询方式",
        ("受理条件", "承诺办结时限", "咨询方式"),
        (
            "请核对“{title}”的受理条件、承诺办结时限和咨询方式。",
            "“{title}”我想先确认受理条件、多久办完，还有咨询电话。",
        ),
    ),
    (
        "办理形式+在线办理地址+办理流程",
        ("办理形式", "在线办理地址", "办理流程"),
        (
            "“{title}”支持什么办理形式？线上入口和办理流程分别是什么？",
            "如果我要办“{title}”，能不能网办？入口在哪，流程怎么走？",
        ),
    ),
    (
        "办理时间+办理地点+监督投诉方式",
        ("办理时间", "办理地点", "监督投诉方式"),
        (
            "“{title}”的办理时间、办理地点和监督投诉方式分别是什么？",
            "我去办“{title}”前，想确认办公时间、办理地点和投诉渠道。",
        ),
    ),
)
REALISTIC_PREFIXES = (
    "我想问下",
    "麻烦帮我看下",
    "我想确认一下",
    "我现在想办",
    "帮我查下",
    "想咨询下",
)
REALISTIC_SUFFIXES = (
    "，具体怎么办？",
    "，这个要怎么弄？",
    "，我该准备什么？",
    "，线上能办吗？",
    "，去哪里办比较准？",
)


@dataclass(slots=True)
class SourceRecord:
    record_id: str
    source_kind: str
    source_file: str
    source_section: str
    knowledge_id: str
    title: str
    district: str
    question: str
    answer: str
    similar_questions: list[str]
    fields: dict[str, str]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _slug(text: str, *, prefix: str) -> str:
    digest = hashlib.sha1(_text(text).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _normalize_question(text: str) -> str:
    text = _text(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip("，,。；; ")


def _split_service_blocks(text: str) -> list[str]:
    return [block.strip() for block in text.split(SERVICE_ITEM_SEPARATOR) if block.strip()]


def _split_multi_value_text(text: str) -> list[str]:
    raw = _text(text)
    if not raw:
        return []
    parts = re.split(r"[；;、\n]+", raw)
    if len(parts) <= 1:
        parts = re.split(r"[，,]", raw)
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = _normalize_question(part)
        if len(item) < 4 or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _sentence_segments(text: str, *, limit: int = 3) -> list[str]:
    raw = _text(text).replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"\s+", " ", raw)
    raw = re.sub(r"(?<!\d)(\d+)[.、]", r"\n\1.", raw)
    segments = re.split(r"[\n；;。]+", raw)
    out: list[str] = []
    seen: set[str] = set()
    for segment in segments:
      s = _normalize_question(segment)
      if len(s) < 4:
          continue
      if s in seen:
          continue
      seen.add(s)
      out.append(s)
      if len(out) >= limit:
          break
    return out


def _clause_terms_from_segment(segment: str) -> list[str]:
    text = _text(segment)
    if not text:
        return []
    compact = URL_RE.sub("", text).strip()
    terms: list[str] = []
    phones = PHONE_RE.findall(compact)
    for phone in phones:
        if phone and phone not in terms:
            terms.append(phone)
    for marker in ("不收费", "免费", "收费", "线上", "窗口", "办理地点", "咨询方式"):
        if marker in compact and marker not in terms:
            terms.append(marker)
    compact = compact[:72].strip()
    if compact and compact not in terms:
        terms.insert(0, compact)
    return terms[:3]


def _source_section(path: Path) -> str:
    return _text(path.parent.name)


def _infer_district(path: Path, title: str = "") -> str:
    text = f"{path.name} {title}"
    for district in KNOWN_DISTRICTS:
        if district in text:
            return district
    return "常州市"


def _knowledge_id_for(path: Path, *, title: str = "") -> str:
    district = _infer_district(path, title)
    if district == "常州市":
        return "changzhou_city_service"
    return f"changzhou_{district}_service"


def parse_service_item_file(path: Path) -> list[SourceRecord]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    records: list[SourceRecord] = []
    for index, block in enumerate(_split_service_blocks(text), start=1):
        title = ""
        fields: dict[str, str] = {}
        for raw in block.splitlines():
            line = raw.strip()
            if not line:
                continue
            title_match = SERVICE_TITLE_RE.match(line)
            if title_match:
                title = _text(title_match.group("title"))
                continue
            field_match = FIELD_RE.match(line)
            if field_match:
                fields[_text(field_match.group("name"))] = _text(field_match.group("value"))
        if not title or not fields:
            continue
        district = _infer_district(path, title)
        question = f"请问“{title}”这个事项怎么办理？"
        answer = "；".join(f"{key}：{value}" for key, value in fields.items() if _text(value))
        records.append(
            SourceRecord(
                record_id=f"svc-{_slug(str(path), prefix='file')}-{index:05d}",
                source_kind="service_item",
                source_file=str(path),
                source_section=_source_section(path),
                knowledge_id=_knowledge_id_for(path, title=title),
                title=title,
                district=district,
                question=question,
                answer=answer,
                similar_questions=[],
                fields=fields,
            )
        )
    return records


def parse_qa_text_file(path: Path) -> list[SourceRecord]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    records: list[SourceRecord] = []
    for index, block in enumerate(_split_service_blocks(text), start=1):
        question = ""
        answer_lines: list[str] = []
        title = ""
        for raw in block.splitlines():
            line = raw.strip()
            if not line:
                continue
            q_match = QA_QUESTION_RE.match(line)
            if q_match:
                question = _normalize_question(q_match.group("question"))
                title = question
                continue
            a_match = QA_ANSWER_RE.match(line)
            if a_match:
                answer_lines.append(_text(a_match.group("answer")))
                continue
            if QA_SOURCE_RE.match(line):
                continue
            if answer_lines:
                answer_lines.append(line)
        answer = _normalize_question(" ".join(answer_lines))
        if not question or not answer:
            continue
        district = _infer_district(path, title)
        records.append(
            SourceRecord(
                record_id=f"qa-{_slug(str(path), prefix='file')}-{index:05d}",
                source_kind="qa_text",
                source_file=str(path),
                source_section=_source_section(path),
                knowledge_id=_knowledge_id_for(path, title=title),
                title=title,
                district=district,
                question=question,
                answer=answer,
                similar_questions=[],
                fields={},
            )
        )
    return records


def parse_one_thing_file(path: Path) -> list[SourceRecord]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    title = ""
    section = ""
    sections: dict[str, list[str]] = defaultdict(list)
    records: list[SourceRecord] = []

    def flush() -> None:
        nonlocal title, section, sections
        if not title:
            return
        materials = _text(" ".join(sections.get("申请材料", [])))
        guide = _text(" ".join(sections.get("办理须知", [])))
        channel = _text(" ".join(sections.get("办理渠道", []) or sections.get("在线办理地址", [])))
        answer_parts = [part for part in (guide, materials, channel) if part]
        records.append(
            SourceRecord(
                record_id=f"onething-{_slug(str(path)+title, prefix='ot')}",
                source_kind="one_thing",
                source_file=str(path),
                source_section=_source_section(path),
                knowledge_id="changzhou_city_service",
                title=title,
                district="常州市",
                question=f"{title}怎么办？",
                answer="；".join(answer_parts),
                similar_questions=[],
                fields={
                    key: _text(" ".join(values))
                    for key, values in sections.items()
                    if _text(" ".join(values))
                },
            )
        )
        title = ""
        section = ""
        sections = defaultdict(list)

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            flush()
            title = _normalize_question(line.strip("[]"))
            continue
        if title and not re.match(r"^\d+[．.、]", line) and len(line) <= 20 and "：" not in line:
            section = line
            continue
        if title and section:
            sections[section].append(line)
    flush()
    return [item for item in records if item.answer]


def parse_xlsx_faq_file(path: Path) -> list[SourceRecord]:
    frame = pd.read_excel(path)
    question_col = next((col for col in frame.columns if _text(col) == "问题"), None)
    answer_col = next((col for col in frame.columns if _text(col) == "答案"), None)
    similar_col = next((col for col in frame.columns if _text(col) == "相似问法"), None)
    if question_col is None or answer_col is None:
        return []

    records: list[SourceRecord] = []
    for index, row in frame.iterrows():
        question = _normalize_question(row.get(question_col))
        answer = _normalize_question(row.get(answer_col))
        if not question or not answer:
            continue
        title = question
        similar_questions = _split_multi_value_text(row.get(similar_col)) if similar_col else []
        district = _infer_district(path, title)
        records.append(
            SourceRecord(
                record_id=f"xlsx-{_slug(str(path), prefix='file')}-{index:05d}",
                source_kind="qa_xlsx",
                source_file=str(path),
                source_section=_source_section(path),
                knowledge_id=_knowledge_id_for(path, title=title),
                title=title,
                district=district,
                question=question,
                answer=answer,
                similar_questions=similar_questions,
                fields={},
            )
        )
    return records


def parse_docx_qa_file(path: Path) -> list[SourceRecord]:
    paragraphs = [_normalize_question(p.text) for p in DocxDocument(path).paragraphs if _text(p.text)]
    records: list[SourceRecord] = []
    index = 0
    for i in range(len(paragraphs) - 1):
        question = paragraphs[i]
        answer_line = paragraphs[i + 1]
        if not answer_line.startswith("答："):
            continue
        answer = _normalize_question(answer_line.removeprefix("答："))
        if not question or not answer:
            continue
        title = question
        district = _infer_district(path, title)
        records.append(
            SourceRecord(
                record_id=f"docx-{_slug(str(path), prefix='file')}-{index:05d}",
                source_kind="qa_docx",
                source_file=str(path),
                source_section=_source_section(path),
                knowledge_id=_knowledge_id_for(path, title=title),
                title=title,
                district=district,
                question=question,
                answer=answer,
                similar_questions=[],
                fields={},
            )
        )
        index += 1
    return records


def load_corpus_records(corpus_root: Path) -> dict[str, list[SourceRecord]]:
    service_records: list[SourceRecord] = []
    qa_records: list[SourceRecord] = []
    one_thing_records: list[SourceRecord] = []

    for path in sorted((corpus_root / "01政务服务事项知识").glob("*.txt")):
        service_records.extend(parse_service_item_file(path))

    for path in sorted((corpus_root / "06各区常见问题").glob("*.txt")):
        qa_records.extend(parse_qa_text_file(path))
    for path in sorted((corpus_root / "03常州市常见问题").glob("*.txt")):
        qa_records.extend(parse_qa_text_file(path))
    for path in sorted((corpus_root / "04专题常见问答").glob("*.txt")):
        qa_records.extend(parse_qa_text_file(path))
    for path in sorted((corpus_root / "03常州市常见问题").glob("*.xlsx")):
        qa_records.extend(parse_xlsx_faq_file(path))
    for path in sorted((corpus_root / "05业务部门常见问题").glob("*.docx")):
        qa_records.extend(parse_docx_qa_file(path))
    for path in sorted((corpus_root / "02高效办成一件事").glob("*.txt")):
        one_thing_records.extend(parse_one_thing_file(path))

    return {
        "service_records": service_records,
        "qa_records": qa_records,
        "one_thing_records": one_thing_records,
    }


def _field_aliases_for(fields: Iterable[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for field in fields:
        aliases = FIELD_ALIASES.get(_text(field))
        if aliases:
            out[_text(field)] = list(aliases)
    return out


def _build_service_case(
    record: SourceRecord,
    *,
    case_type: str,
    question: str,
    fields: list[str],
    variant_reason: str,
) -> dict[str, Any]:
    clauses = []
    subquestions = []
    for index, field in enumerate(fields, start=1):
        value = _text(record.fields.get(field))
        if not value:
            continue
        clause_id = f"{field}-{index}"
        clauses.append(
            {
                "id": clause_id,
                "required_terms": [f"事项名称：{record.title}", f"{field}：", value],
                "match_scope": "record",
            }
        )
        subquestions.append({"id": field, "required_clause_ids": [clause_id]})

    return {
        "id": _slug(f"{case_type}:{record.record_id}:{question}", prefix="case"),
        "knowledge_id": record.knowledge_id,
        "dify_inputs": {"areaName": record.district} if record.district else {},
        "question": question,
        "query": question,
        "case_type": case_type,
        "source_file": record.source_file,
        "source_section": record.source_section,
        "source_record_title": record.title,
        "subquestions": subquestions,
        "evidence_clauses": clauses,
        "min_evidence_coverage": 0.67,
        "min_subquestion_coverage": 0.67,
        "max_wrong_evidence_rate": 0.75,
        "dimension_signature": "+".join(fields),
        "dimension_fields": list(fields),
        "case_generation": GENERATION_NAME,
        "qa_like_source": False,
        "answer_term_aliases": _field_aliases_for(fields),
        "expected_answer": "；".join(f"{field}：{_text(record.fields.get(field))}" for field in fields if _text(record.fields.get(field))),
        "source_case_id": record.record_id,
        "generation_reason": variant_reason,
    }


def _available_service_profiles(record: SourceRecord) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    available = set(record.fields.keys())
    return [profile for profile in DIMENSION_PROFILES if set(profile[1]).issubset(available)]


def _humanize_title(title: str) -> str:
    text = _normalize_question(title)
    text = re.sub(r"（.*?）|\(.*?\)", "", text).strip()
    text = text.removeprefix("核发").removeprefix("办理")
    if len(text) <= 16:
        return text
    for marker in ("申请", "补办", "补领", "变更", "登记", "备案", "许可", "注销", "补贴", "证明"):
        if marker in text:
            left, _sep, _right = text.partition(marker)
            candidate = f"{left}{marker}".strip()
            if 3 <= len(candidate) <= 16:
                return candidate
    return f"{text[:12]}这类业务"


def _build_service_user_question(record: SourceRecord, fields: list[str], rng: random.Random) -> str:
    subject = _humanize_title(record.title)
    dims = "、".join(FIELD_ALIASES.get(field, [field])[0] for field in fields)
    prefix = rng.choice(REALISTIC_PREFIXES)
    suffix = rng.choice(REALISTIC_SUFFIXES)
    area = record.district if record.district and record.district != "常州市" else ""
    area_prefix = f"{area}" if area else ""
    return _normalize_question(f"{prefix}{area_prefix}{subject}，{dims}{suffix}")


def _build_answer_clauses(answer: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    clauses: list[dict[str, Any]] = []
    subquestions: list[dict[str, Any]] = []
    for index, segment in enumerate(_sentence_segments(answer), start=1):
        clause_id = f"answer-{index}"
        clauses.append(
            {
                "id": clause_id,
                "required_terms": _clause_terms_from_segment(segment) or [segment[:72]],
                "match_scope": "record",
            }
        )
        subquestions.append(
            {
                "id": f"要点{index}",
                "required_clause_ids": [clause_id],
                "required_terms": _clause_terms_from_segment(segment) or [segment[:72]],
            }
        )
    return clauses, subquestions


def _build_qa_case(
    record: SourceRecord,
    *,
    case_type: str,
    question: str,
    variant_reason: str,
) -> dict[str, Any]:
    clauses, subquestions = _build_answer_clauses(record.answer)
    return {
        "id": _slug(f"{case_type}:{record.record_id}:{question}", prefix="case"),
        "knowledge_id": record.knowledge_id,
        "dify_inputs": {"areaName": record.district} if record.district else {},
        "question": question,
        "query": question,
        "case_type": case_type,
        "source_file": record.source_file,
        "source_section": record.source_section,
        "source_record_title": record.title,
        "subquestions": subquestions or [{"id": "回答", "required_terms": _clause_terms_from_segment(record.answer[:72]) or [record.answer[:72]]}],
        "evidence_clauses": clauses or [{"id": "answer-1", "required_terms": _clause_terms_from_segment(record.answer[:72]) or [record.answer[:72]]}],
        "min_evidence_coverage": 0.5,
        "min_subquestion_coverage": 0.5,
        "max_wrong_evidence_rate": 0.8,
        "dimension_signature": "qa_answer",
        "dimension_fields": ["答案要点"],
        "case_generation": GENERATION_NAME,
        "qa_like_source": True,
        "expected_answer": record.answer,
        "source_case_id": record.record_id,
        "generation_reason": variant_reason,
    }


def _build_one_thing_case(record: SourceRecord, rng: random.Random) -> dict[str, Any]:
    fields = []
    for candidate in ("申请材料", "办理须知", "办理渠道", "在线办理地址"):
        if _text(record.fields.get(candidate)):
            fields.append(candidate)
        if len(fields) >= 2:
            break
    if not fields:
        fields = list(record.fields)[:2] or ["办理须知"]
    question = _normalize_question(
        f"{rng.choice(REALISTIC_PREFIXES)}{record.title}，{'、'.join(fields)}这几块能不能帮我说人话讲一下？"
    )
    return _build_service_case(
        record,
        case_type="one_thing_user",
        question=question,
        fields=fields,
        variant_reason="one_thing_colloquial",
    )


def build_case_payload(
    *,
    records: dict[str, list[SourceRecord]],
    qa_count: int,
    service_count: int,
    user_count: int,
    target_total: int,
    seed: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    effective_qa_count = max(0, int(qa_count))
    effective_service_count = max(0, int(service_count))
    effective_user_count = max(0, int(user_count))
    if int(target_total or 0) > 0:
        effective_user_count = max(
            0,
            int(target_total) - effective_qa_count - effective_service_count,
        )

    def push(case: dict[str, Any]) -> bool:
        question = _normalize_question(case.get("question"))
        if not question or question in seen_questions:
            return False
        seen_questions.add(question)
        cases.append(case)
        return True

    qa_records = [record for record in records["qa_records"] if _text(record.question) and _text(record.answer)]
    service_records = [record for record in records["service_records"] if _available_service_profiles(record)]
    one_thing_records = [record for record in records["one_thing_records"] if record.fields]
    rng.shuffle(qa_records)
    rng.shuffle(service_records)
    rng.shuffle(one_thing_records)

    # 1) exact QA bucket
    qa_bucket = 0
    for record in qa_records:
        if qa_bucket >= effective_qa_count:
            break
        if push(_build_qa_case(record, case_type="qa_exact", question=record.question, variant_reason="source_question")):
            qa_bucket += 1

    # 2) service-item direct bucket
    service_bucket = 0
    service_profile_index = 0
    while service_bucket < effective_service_count and service_records:
        record = service_records[service_bucket % len(service_records)]
        profiles = _available_service_profiles(record)
        if not profiles:
            service_bucket += 0
            continue
        profile = profiles[service_profile_index % len(profiles)]
        question = rng.choice(profile[2]).format(title=record.title)
        if push(
            _build_service_case(
                record,
                case_type="service_direct",
                question=question,
                fields=list(profile[1]),
                variant_reason=f"service_profile:{profile[0]}",
            )
        ):
            service_bucket += 1
        service_profile_index += 1
        if service_profile_index > len(service_records) * 8:
            break

    # 3) realistic user bucket: first use natural QA/similar questions, then service/one-thing oralized questions.
    user_bucket = 0
    user_candidates: list[dict[str, Any]] = []
    for record in qa_records:
        variants = [record.question, *record.similar_questions]
        for variant in variants:
            question = _normalize_question(variant)
            if question:
                user_candidates.append(
                    _build_qa_case(
                        record,
                        case_type="user_simulated",
                        question=question,
                        variant_reason="qa_or_similar_question",
                    )
                )
    for record in one_thing_records:
        user_candidates.append(_build_one_thing_case(record, rng))
    for record in service_records:
        short_title = _humanize_title(record.title)
        if len(short_title) > 18:
            continue
        profiles = _available_service_profiles(record)
        if not profiles:
            continue
        profile = rng.choice(profiles)
        user_candidates.append(
            _build_service_case(
                record,
                case_type="user_simulated",
                question=_build_service_user_question(record, list(profile[1]), rng),
                fields=list(profile[1]),
                variant_reason=f"service_colloquial:{profile[0]}",
            )
        )

    rng.shuffle(user_candidates)
    for case in user_candidates:
        if user_bucket >= effective_user_count:
            break
        if push(case):
            user_bucket += 1

    payload = {
        "schema": CASES_SCHEMA,
        "description": "Changzhou corpus-grounded evaluation pack built from raw government-service knowledge files.",
        "cases": cases,
        "generation_policy": {
            "name": GENERATION_NAME,
            "requested": {
                "qa_count": qa_count,
                "service_count": service_count,
                "user_count": user_count,
                "target_total": int(target_total or 0),
            },
            "effective": {
                "qa_count": effective_qa_count,
                "service_count": effective_service_count,
                "user_count": effective_user_count,
            },
            "summary": {
                "total": len(cases),
                "case_types": dict(Counter(_text(case.get("case_type")) for case in cases)),
                "source_sections": dict(Counter(_text(case.get("source_section")) for case in cases)),
                "knowledge_ids": dict(Counter(_text(case.get("knowledge_id")) for case in cases)),
            },
        },
    }
    return payload


def build_truth_manifest(cases: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for case in cases:
        items.append(
            {
                "case_id": _text(case.get("id")),
                "question": _text(case.get("question") or case.get("query")),
                "case_type": _text(case.get("case_type")),
                "knowledge_id": _text(case.get("knowledge_id")),
                "source_file": _text(case.get("source_file")),
                "source_section": _text(case.get("source_section")),
                "source_record_title": _text(case.get("source_record_title")),
                "dimension_fields": list(case.get("dimension_fields") or []),
                "subquestion_ids": [
                    _text(item.get("id") if isinstance(item, dict) else item)
                    for item in (case.get("subquestions") or [])
                    if _text(item.get("id") if isinstance(item, dict) else item)
                ],
                "evidence_clause_ids": [
                    _text(item.get("id") if isinstance(item, dict) else item)
                    for item in (case.get("evidence_clauses") or [])
                    if _text(item.get("id") if isinstance(item, dict) else item)
                ],
                "expected_answer": _text(case.get("expected_answer")),
            }
        )
    return {
        "schema": TRUTH_SCHEMA,
        "items": items,
        "summary": {
            "total": len(items),
            "case_types": dict(Counter(_text(item.get("case_type")) for item in items)),
        },
    }


def load_regression_bundle(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("regression bundle must be a JSON object")
    if _text(payload.get("schema")) != REGRESSION_CASE_BUNDLE_SCHEMA_V1:
        raise ValueError("unsupported regression bundle schema")
    if not _text(payload.get("dataset_id")):
        raise ValueError("regression bundle missing dataset_id")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("regression bundle items[] is empty")
    return {"schema": payload.get("schema"), "dataset_id": payload.get("dataset_id"), "items": [dict(item) for item in items if isinstance(item, dict)]}


def _detect_local_dataset_id(corpus_root: Path, *, tenant_id: UUID) -> str:
    corpus_filenames = {path.name for path in corpus_root.rglob("*") if path.is_file()}
    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(Document.tenant_id == tenant_id, Document.disabled_at.is_(None))
            .all()
        )
        counts: Counter[str] = Counter()
        for doc in docs:
            if _text(doc.filename) in corpus_filenames and doc.dataset_id:
                counts[str(doc.dataset_id)] += 1
        if not counts:
            return ""
        return counts.most_common(1)[0][0]
    finally:
        db.close()


def _iter_search_terms(case: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for clause in case.get("evidence_clauses") or []:
        if not isinstance(clause, dict):
            continue
        for term in clause.get("required_terms") or []:
            text = _text(term)
            if not text:
                continue
            if text.startswith("事项名称：") or text.endswith("：") or len(text) < 4:
                continue
            if text in seen:
                continue
            seen.add(text)
            out.append(text)
    expected = _text(case.get("expected_answer"))
    for segment in _sentence_segments(expected, limit=2):
        if segment not in seen:
            seen.add(segment)
            out.append(segment)
    question = _text(case.get("question"))
    if question and question not in seen:
        out.append(question[:32])
    out.sort(key=len, reverse=True)
    return out[:8]


def resolve_reference_sources(
    cases: list[dict[str, Any]],
    *,
    dataset_id: str,
    tenant_id: str,
    max_refs_per_case: int = 3,
) -> tuple[dict[str, Any], dict[str, Any]]:
    db = SessionLocal()
    dataset_uuid = UUID(str(dataset_id))
    tenant_uuid = UUID(str(tenant_id))
    resolved_items: list[dict[str, Any]] = []
    unresolved_items: list[dict[str, Any]] = []
    term_cache: dict[str, list[dict[str, Any]]] = {}
    try:
      for case in cases:
        refs: list[dict[str, Any]] = []
        for term in _iter_search_terms(case):
            if term not in term_cache:
                rows = (
                    db.query(DocumentChunk, Document.filename)
                    .join(
                        Document,
                        and_(
                            Document.id == DocumentChunk.document_id,
                            Document.tenant_id == DocumentChunk.tenant_id,
                        ),
                    )
                    .filter(
                        DocumentChunk.tenant_id == tenant_uuid,
                        Document.dataset_id == dataset_uuid,
                        DocumentChunk.disabled_at.is_(None),
                        DocumentChunk.content.ilike(f"%{term}%"),
                    )
                    .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
                    .limit(10)
                    .all()
                )
                term_cache[term] = [
                    {
                        "document_id": str(chunk.document_id),
                        "chunk_id": str(chunk.id),
                        "chunk_index": int(chunk.chunk_index or 0),
                        "page_number": int(chunk.page_number) if chunk.page_number is not None else None,
                        "start_char": int(chunk.start_char) if chunk.start_char is not None else None,
                        "end_char": int(chunk.end_char) if chunk.end_char is not None else None,
                        "quote": _text(chunk.content)[:400],
                        "label": f"term:{term[:32]}",
                        "document_name": _text(filename),
                    }
                    for chunk, filename in rows
                ]
            for item in term_cache.get(term, []):
                if any(existing["chunk_id"] == item["chunk_id"] for existing in refs):
                    continue
                refs.append({k: v for k, v in item.items() if k != "document_name"})
                if len(refs) >= max_refs_per_case:
                    break
            if len(refs) >= max_refs_per_case:
                break

        target = {
            "question": _text(case.get("question")),
            "expected_answer": _text(case.get("expected_answer")) or None,
            "reference_sources": refs,
            "tags": [
                _text(case.get("case_type")),
                _text(case.get("source_section")),
                _text(case.get("knowledge_id")),
            ],
            "extra": {
                "source_file": _text(case.get("source_file")),
                "source_record_title": _text(case.get("source_record_title")),
                "case_generation": _text(case.get("case_generation")),
                "dimension_fields": list(case.get("dimension_fields") or []),
            },
        }
        if refs:
            resolved_items.append(target)
        else:
            unresolved_items.append(
                {
                    "case_id": _text(case.get("id")),
                    "question": _text(case.get("question")),
                    "source_file": _text(case.get("source_file")),
                    "search_terms": _iter_search_terms(case),
                }
            )
    finally:
        db.close()

    bundle = {
        "schema": REGRESSION_CASE_BUNDLE_SCHEMA_V1,
        "dataset_id": str(dataset_uuid),
        "items": resolved_items,
    }
    report = {
        "dataset_id": str(dataset_uuid),
        "resolved": len(resolved_items),
        "unresolved": len(unresolved_items),
        "unresolved_items": unresolved_items,
    }
    return bundle, report


def import_regression_bundle(
    bundle: dict[str, Any],
    *,
    base_url: str,
    tenant_id: str,
    user_id: str,
    overwrite: bool,
    max_items: int,
    batch_size: int = 200,
    timeout: float = 60.0,
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "X-Tenant-ID": _text(tenant_id),
        "X-User-ID": _text(user_id),
        "X-Account-ID": _text(user_id),
    }
    all_items = list(bundle.get("items") or [])
    batch = max(1, min(int(batch_size or 200), 500))
    aggregate = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "created_case_ids": [],
        "updated_case_ids": [],
        "skipped_case_ids": [],
    }
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=float(timeout), trust_env=False) as client:
        for offset in range(0, len(all_items), batch):
            chunk = all_items[offset : offset + batch]
            payload = {
                "dataset_id": bundle["dataset_id"],
                "overwrite": bool(overwrite),
                "max_items": min(int(max_items), len(chunk)),
                "items": chunk,
            }
            response = client.post("/evaluations/ragas/regression/cases/import", json=payload, headers=headers)
            response.raise_for_status()
            current = response.json()
            aggregate["created"] += int(current.get("created") or 0)
            aggregate["updated"] += int(current.get("updated") or 0)
            aggregate["skipped"] += int(current.get("skipped") or 0)
            aggregate["errors"].extend(list(current.get("errors") or []))
            aggregate["created_case_ids"].extend(list(current.get("created_case_ids") or []))
            aggregate["updated_case_ids"].extend(list(current.get("updated_case_ids") or []))
            aggregate["skipped_case_ids"].extend(list(current.get("skipped_case_ids") or []))
            print(
                json.dumps(
                    {
                        "stage": "regression_import",
                        "batch_start": offset,
                        "batch_size": len(chunk),
                        "created_total": aggregate["created"],
                        "updated_total": aggregate["updated"],
                        "skipped_total": aggregate["skipped"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return aggregate


def create_retrieval_only_run(
    *,
    dataset_id: str,
    case_ids: list[str],
    base_url: str,
    tenant_id: str,
    user_id: str,
    max_cases: int,
    timeout: float = 60.0,
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "X-Tenant-ID": _text(tenant_id),
        "X-User-ID": _text(user_id),
        "X-Account-ID": _text(user_id),
    }
    payload = {
        "dataset_id": dataset_id,
        "case_ids": case_ids,
        "metrics": [],
        "skip_empty_contexts": True,
        "max_cases": int(max_cases),
    }
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=float(timeout), trust_env=False) as client:
        response = client.post("/evaluations/ragas/regression/runs", json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


def create_retrieval_only_sharded_runs(
    *,
    dataset_id: str,
    case_ids: list[str],
    base_url: str,
    tenant_id: str,
    user_id: str,
    shard_size: int = 500,
    timeout: float = 60.0,
) -> dict[str, Any]:
    shard = max(1, min(int(shard_size or 500), 500))
    run_ids: list[str] = []
    run_payloads: list[dict[str, Any]] = []
    for offset in range(0, len(case_ids), shard):
        batch = case_ids[offset : offset + shard]
        if not batch:
            continue
        run = create_retrieval_only_run(
            dataset_id=dataset_id,
            case_ids=batch,
            base_url=base_url,
            tenant_id=tenant_id,
            user_id=user_id,
            max_cases=len(batch),
            timeout=timeout,
        )
        run_ids.append(_text(run.get("id")))
        run_payloads.append(
            {
                "id": _text(run.get("id")),
                "status": _text(run.get("status")),
                "cases": len(batch),
                "offset": offset,
            }
        )
    return {
        "dataset_id": dataset_id,
        "requested_cases": len(case_ids),
        "shard_size": shard,
        "run_ids": run_ids,
        "runs": run_payloads,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Changzhou evaluation benchmark + regression bundles from raw corpus.")
    parser.add_argument("--corpus-root", default=DEFAULT_CORPUS_ROOT)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--qa-count", type=int, default=100)
    parser.add_argument("--service-count", type=int, default=200)
    parser.add_argument("--user-count", type=int, default=800)
    parser.add_argument("--target-total", type=int, default=0, help="Optional exact total cap. When set, qa_count/service_count are preserved and user_count is trimmed to fit.")
    parser.add_argument("--seed", type=int, default=20260709)
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--dataset-id", default="", help="Existing MimirQ dataset id for live reference resolution/import.")
    parser.add_argument("--resume-bundle", default="", help="Existing regression bundle JSON. When set, skip corpus parsing/live reference resolution and continue from this bundle.")
    parser.add_argument("--resolve-live-refs", action="store_true")
    parser.add_argument("--import-regression", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--create-retrieval-run", action="store_true")
    parser.add_argument("--run-shard-size", type=int, default=500)
    parser.add_argument("--import-batch-size", type=int, default=200)
    parser.add_argument("--api-timeout", type=float, default=60.0)
    parser.add_argument("--backend-base-url", default=DEFAULT_BACKEND_BASE_URL)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = None
    cases: list[dict[str, Any]] = []
    dataset_id = _text(args.dataset_id)
    resolved_bundle = None
    if _text(args.resume_bundle):
        resolved_bundle = load_regression_bundle(str(args.resume_bundle))
        dataset_id = dataset_id or _text(resolved_bundle.get("dataset_id"))
        cases = []
    else:
        corpus_root = Path(args.corpus_root)
        if not corpus_root.is_dir():
            print(f"[changzhou-gov-eval-pack] ERROR: corpus root not found: {corpus_root}", file=sys.stderr)
            return 2

        records = load_corpus_records(corpus_root)
        payload = build_case_payload(
            records=records,
            qa_count=int(args.qa_count),
            service_count=int(args.service_count),
            user_count=int(args.user_count),
            target_total=int(args.target_total or 0),
            seed=int(args.seed),
        )
        cases = payload["cases"]

        (out_dir / "cases_1000.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        truth = build_truth_manifest(cases)
        (out_dir / "truth_manifest.json").write_text(
            json.dumps(truth, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        if not dataset_id and (args.resolve_live_refs or args.import_regression or args.create_retrieval_run):
            dataset_id = _detect_local_dataset_id(corpus_root, tenant_id=UUID(str(args.tenant_id)))

    import_result = None
    run_result = None
    if args.resolve_live_refs or args.import_regression or args.create_retrieval_run or _text(args.resume_bundle):
        if not dataset_id:
            print("[changzhou-gov-eval-pack] ERROR: could not auto-detect dataset_id; pass --dataset-id explicitly", file=sys.stderr)
            return 2
        if resolved_bundle is None:
            resolved_bundle, resolve_report = resolve_reference_sources(
                cases,
                dataset_id=dataset_id,
                tenant_id=str(args.tenant_id),
            )
            (out_dir / "regression_bundle.json").write_text(
                json.dumps(resolved_bundle, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (out_dir / "reference_resolution_report.json").write_text(
                json.dumps(resolve_report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            (out_dir / "regression_bundle.json").write_text(
                json.dumps(resolved_bundle, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        if args.import_regression:
            import_result = import_regression_bundle(
                resolved_bundle,
                base_url=str(args.backend_base_url),
                tenant_id=str(args.tenant_id),
                user_id=str(args.user_id),
                overwrite=bool(args.overwrite),
                max_items=len(resolved_bundle["items"]),
                batch_size=int(args.import_batch_size),
                timeout=float(args.api_timeout),
            )
            (out_dir / "regression_import_result.json").write_text(
                json.dumps(import_result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        if args.create_retrieval_run:
            if not import_result:
                print("[changzhou-gov-eval-pack] ERROR: --create-retrieval-run requires --import-regression", file=sys.stderr)
                return 2
            case_ids = [
                *[str(x) for x in import_result.get("created_case_ids") or []],
                *[str(x) for x in import_result.get("updated_case_ids") or []],
                *[str(x) for x in import_result.get("skipped_case_ids") or []],
            ]
            case_ids = [item for item in case_ids if _text(item)]
            run_result = create_retrieval_only_sharded_runs(
                dataset_id=dataset_id,
                case_ids=case_ids,
                base_url=str(args.backend_base_url),
                tenant_id=str(args.tenant_id),
                user_id=str(args.user_id),
                shard_size=int(args.run_shard_size),
                timeout=float(args.api_timeout),
            )
            (out_dir / "retrieval_only_run.json").write_text(
                json.dumps(run_result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    summary = {
        "cases_total": len(cases) if cases else len((resolved_bundle or {}).get("items") or []),
        "case_type_counts": (payload or {}).get("generation_policy", {}).get("summary", {}).get("case_types", {}),
        "service_records": len(records["service_records"]) if 'records' in locals() else None,
        "qa_records": len(records["qa_records"]) if 'records' in locals() else None,
        "one_thing_records": len(records["one_thing_records"]) if 'records' in locals() else None,
        "dataset_id": dataset_id or None,
        "resolved_bundle_items": len((resolved_bundle or {}).get("items") or []) if resolved_bundle else 0,
        "imported_created": (import_result or {}).get("created") if import_result else None,
        "imported_updated": (import_result or {}).get("updated") if import_result else None,
        "retrieval_run_ids": list((run_result or {}).get("run_ids") or []),
        "output_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
