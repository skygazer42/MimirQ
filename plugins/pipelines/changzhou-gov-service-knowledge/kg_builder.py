from __future__ import annotations

import re
from typing import Any

from langchain_core.documents import Document

_KG_BUILDER = "changzhou_gov_service_knowledge_v1"
_KG_ENTITY_NAME_MAX = 500
_KG_EVENT_TITLE_MAX = 255
_MATERIAL_BOUNDARY_RE = re.compile(r"\s+(?=\d{1,3}[、.．])")
_LEADING_NUMBER_RE = re.compile(r"^\d{1,3}[、.．]\s*")
_TEXT_SPLIT_RE = re.compile(r"[、,，；;]\s*")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_present(meta: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _text(meta.get(key))
        if value:
            return value
    return ""


def _first_line(text: str) -> str:
    for line in str(text or "").splitlines():
        value = line.strip()
        if value:
            return value
    return ""


def _line_value(text: str, label: str) -> str:
    prefix = f"{label}："
    alt = f"{label}:"
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
        if line.startswith(alt):
            return line[len(alt) :].strip()
    return ""


def _clamp(value: Any, limit: int = 180) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _split_simple_list(value: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in _TEXT_SPLIT_RE.split(_text(value)):
        item = part.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _material_items(value: Any, *, limit: int = 12) -> list[str]:
    text = _text(value)
    if not text:
        return []
    parts = [part.strip() for part in _MATERIAL_BOUNDARY_RE.split(text) if part.strip()]
    if len(parts) <= 1:
        parts = [part.strip() for part in re.split(r"[\n；;]", text) if part.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        item = _LEADING_NUMBER_RE.sub("", part).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(_clamp(item, 120))
        if len(out) >= limit:
            break
    return out


def _entity(
    name: Any,
    type_: str,
    *,
    role: str,
    description: Any = "",
    evidence_quote: Any = "",
) -> dict[str, Any] | None:
    raw_name = _text(name)
    if not raw_name:
        return None
    text = _clamp(raw_name, _KG_ENTITY_NAME_MAX)
    return {
        "name": text,
        "normalized_name": _clamp(raw_name.casefold(), _KG_ENTITY_NAME_MAX),
        "type": type_,
        "role": role,
        "description": _clamp(description, 300),
        "evidence_quote": _clamp(evidence_quote or text, 240),
    }


def _dedupe_entities(items: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        if not item:
            continue
        key = (_text(item.get("type")) or "unknown", _text(item.get("normalized_name")) or _text(item.get("name")))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _base_references(meta: dict[str, Any]) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    for key in (
        "source",
        "source_file",
        "source_path",
        "source_record_id",
        "source_record_index",
        "source_start_char",
        "source_end_char",
        "chunk_index",
        "chunk_kind",
        "chunk_part_index",
        "chunk_part_total",
        "case_key",
        "section_type",
        "section_label",
        "step_no",
        "source_topic",
        "source_sheet",
        "category_leaf",
        "applicable_area",
        "service_url",
        "content_hash",
        "content_len",
        "pipeline_hash",
        "active_pipeline_hash",
    ):
        value = meta.get(key)
        if value is not None and _text(value):
            refs[key] = value
    return refs


def _base_extra(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "kg_builder": _KG_BUILDER,
        "gov_knowledge_type": _text(meta.get("gov_knowledge_type")),
        "knowledge_section": _text(meta.get("knowledge_section")),
        "source_record_id": _text(meta.get("source_record_id")),
        "chunk_kind": _text(meta.get("chunk_kind")),
    }


def _service_item_event(doc: Document, meta: dict[str, Any], index: int) -> dict[str, Any]:
    fields = meta.get("service_fields") if isinstance(meta.get("service_fields"), dict) else {}
    content = _text(doc.page_content)
    service_name = _first_present(meta, ("service_name",)) or _line_value(content, "事项名称") or _first_line(content)
    district = _text(meta.get("district"))
    chunk_kind = _text(meta.get("chunk_kind"))
    aliases = meta.get("service_aliases") if isinstance(meta.get("service_aliases"), list) else []
    online_url = _first_present(meta, ("online_url", "online_url_normalized")) or _text(fields.get("在线办理地址"))
    title_suffix = "" if chunk_kind in {"", "service_item_full"} else f"｜{chunk_kind}"
    summary_bits = [
        f"区县：{district}" if district else "",
        f"事项：{service_name}" if service_name else "",
        f"办理形式：{fields.get('办理形式')}" if fields.get("办理形式") else "",
        f"受理条件：{_clamp(fields.get('受理条件'), 100)}" if fields.get("受理条件") else "",
        f"办理材料：{_clamp(fields.get('办理材料'), 100)}" if fields.get("办理材料") else "",
    ]
    summary = "；".join(bit for bit in summary_bits if bit) or _clamp(content, 240)

    entities: list[dict[str, Any] | None] = [
        _entity(service_name, "ServiceItem", role="subject", description=summary, evidence_quote=service_name),
        _entity(district, "District", role="district"),
        _entity(meta.get("knowledge_section"), "GovKnowledgeSection", role="knowledge_section"),
        _entity(fields.get("办理地点"), "Location", role="location"),
        _entity(fields.get("受理条件"), "ServiceCondition", role="condition", evidence_quote=fields.get("受理条件")),
        _entity(fields.get("咨询方式"), "Contact", role="contact"),
        _entity(fields.get("监督投诉方式"), "Contact", role="supervision_contact"),
        _entity(online_url, "Url", role="online_url"),
    ]
    for alias in aliases:
        entities.append(_entity(alias, "ServiceItem", role="alias", description=f"{alias} 是 {service_name} 的相似问法"))
    for channel in _split_simple_list(fields.get("办理形式")):
        entities.append(_entity(channel, "Channel", role="service_channel"))
    for material in _material_items(fields.get("办理材料")):
        entities.append(_entity(material, "Material", role="material"))

    return {
        "source_index": index,
        "title": _clamp(f"政务事项：{service_name}{title_suffix}", _KG_EVENT_TITLE_MAX),
        "summary": summary,
        "content": content,
        "references": _base_references(meta),
        "extra_data": {
            **_base_extra(meta),
            "service_name": service_name,
            "district": district,
            "online_url": online_url,
        },
        "entities": _dedupe_entities(entities),
    }


def _qa_event(doc: Document, meta: dict[str, Any], index: int) -> dict[str, Any]:
    content = _text(doc.page_content)
    question = _first_present(meta, ("question",)) or _line_value(content, "问题") or _first_line(content)
    answer = _first_present(meta, ("answer",)) or _line_value(content, "答案")
    department = _text(meta.get("source_department"))
    district = _text(meta.get("district"))
    source_topic = _text(meta.get("source_topic"))
    source_sheet = _text(meta.get("source_sheet"))
    aliases = meta.get("aliases") if isinstance(meta.get("aliases"), list) else []
    keywords = meta.get("keywords") if isinstance(meta.get("keywords"), list) else []
    category_path = meta.get("category_path") if isinstance(meta.get("category_path"), list) else []
    applicable_area = _text(meta.get("applicable_area"))
    service_url = _text(meta.get("service_url"))
    urls = meta.get("urls") if isinstance(meta.get("urls"), list) else []
    if service_url:
        urls = [*urls, service_url]
    entities: list[dict[str, Any] | None] = [
        _entity(question, "Question", role="subject", description=answer, evidence_quote=question),
        _entity(department, "Department", role="source_department"),
        _entity(district, "District", role="district"),
        _entity(source_topic, "GovKnowledgeTopic", role="source_topic"),
        _entity(source_sheet, "SourceSheet", role="source_sheet"),
        _entity(applicable_area, "Region", role="applicable_area"),
        _entity(meta.get("knowledge_section"), "GovKnowledgeSection", role="knowledge_section"),
    ]
    for alias in aliases:
        entities.append(_entity(alias, "Question", role="alias", description=f"{alias} 是该问题的相似问法"))
    for keyword in keywords:
        entities.append(_entity(keyword, "Keyword", role="keyword"))
    for category in category_path:
        entities.append(_entity(category, "BusinessCategory", role="category"))
    for url in urls:
        entities.append(_entity(url, "Url", role="url"))
    return {
        "source_index": index,
        "title": _clamp(f"政务问答：{question}", _KG_EVENT_TITLE_MAX),
        "summary": _clamp(answer or content, 240),
        "content": content,
        "references": _base_references(meta),
        "extra_data": {
            **_base_extra(meta),
            "question": question,
            "source_department": department,
            "source_topic": source_topic,
            "source_sheet": source_sheet,
            "category_path": category_path,
            "category_leaf": _text(meta.get("category_leaf")),
            "applicable_area": applicable_area,
            "service_url": service_url,
            "valid_from": _text(meta.get("valid_from")),
            "valid_to": _text(meta.get("valid_to")),
        },
        "entities": _dedupe_entities(entities),
    }


def _one_thing_event(doc: Document, meta: dict[str, Any], index: int) -> dict[str, Any]:
    content = _text(doc.page_content)
    case_title = _first_present(meta, ("case_title",)) or _first_line(content)
    keywords = meta.get("keywords") if isinstance(meta.get("keywords"), list) else []
    section_type = _text(meta.get("section_type"))
    section_label = _text(meta.get("section_label"))
    related_services = meta.get("related_services") if isinstance(meta.get("related_services"), list) else []
    materials = meta.get("materials") if isinstance(meta.get("materials"), list) else []
    operation_steps = meta.get("operation_steps") if isinstance(meta.get("operation_steps"), list) else []
    urls = meta.get("urls") if isinstance(meta.get("urls"), list) else []
    entities: list[dict[str, Any] | None] = [
        _entity(case_title, "OneThingCase", role="subject", description=_clamp(content, 240), evidence_quote=case_title),
        _entity(meta.get("knowledge_section"), "GovKnowledgeSection", role="knowledge_section"),
        _entity(section_label or section_type, "OneThingSection", role="section"),
    ]
    for keyword in keywords:
        entities.append(_entity(keyword, "Keyword", role="keyword"))
    for service in related_services:
        entities.append(_entity(service, "ServiceItem", role="related_service"))
    for material in materials:
        entities.append(_entity(material, "Material", role="material"))
    for step in operation_steps:
        entities.append(_entity(step, "OperationStep", role="operation_step"))
    for url in urls:
        entities.append(_entity(url, "Url", role="url"))
    title_suffix = f"｜{section_label or section_type}" if section_type else ""
    return {
        "source_index": index,
        "title": _clamp(f"高效办成一件事：{case_title}{title_suffix}", _KG_EVENT_TITLE_MAX),
        "summary": _clamp(content, 240),
        "content": content,
        "references": _base_references(meta),
        "extra_data": {
            **_base_extra(meta),
            "case_title": case_title,
            "case_key": _text(meta.get("case_key")),
            "section_type": section_type,
            "section_label": section_label,
        },
        "entities": _dedupe_entities(entities),
    }


def _text_event(doc: Document, meta: dict[str, Any], index: int) -> dict[str, Any]:
    content = _text(doc.page_content)
    title = _first_present(meta, ("title", "service_name", "case_title", "question")) or _first_line(content) or "政务知识"
    entities = _dedupe_entities(
        [
            _entity(title, "GovKnowledge", role="subject", description=_clamp(content, 240), evidence_quote=title),
            _entity(meta.get("department_domain"), "DepartmentDomain", role="department_domain"),
            _entity(meta.get("knowledge_section"), "GovKnowledgeSection", role="knowledge_section"),
            _entity(meta.get("district"), "District", role="district"),
        ]
    )
    return {
        "source_index": index,
        "title": _clamp(f"政务知识：{title}", _KG_EVENT_TITLE_MAX),
        "summary": _clamp(content, 240),
        "content": content,
        "references": _base_references(meta),
        "extra_data": _base_extra(meta),
        "entities": entities,
    }


def build_kg_events(
    documents: list[Document],
    params: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, doc in enumerate(documents or []):
        meta = dict(doc.metadata or {})
        kind = _text(meta.get("gov_knowledge_type"))
        document_type = _text(meta.get("document_type"))
        if kind == "service_item" or document_type == "gov_service_item":
            events.append(_service_item_event(doc, meta, index))
        elif kind == "qa":
            events.append(_qa_event(doc, meta, index))
        elif kind in {"one_thing_guide", "one_thing_operation"}:
            events.append(_one_thing_event(doc, meta, index))
        else:
            events.append(_text_event(doc, meta, index))
    return events


__all__ = ["build_kg_events"]
