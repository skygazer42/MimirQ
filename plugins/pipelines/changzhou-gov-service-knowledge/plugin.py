from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from gov_service_items import chunk_documents as _chunk_service_items
from gov_service_items import govern_documents as _govern_service_items
from langchain_core.documents import Document

_BLOCK_SEPARATOR_RE = re.compile(r"(?:==|--)##########(?:==|--)")
_TITLE_BRACKET_RE = re.compile(r"^\[(?P<title>.+?)\]\s*$")
_ALIAS_RE = re.compile(r"==##相似问(?:法)?[：:]\s*(?P<value>.+?)##==")
_KEYWORD_RE = re.compile(r"==##(?:关键字|关键词)[：:]\s*(?P<value>.+?)##==")
_QUESTION_RE = re.compile(r"问题[：:]\s*\[?(?P<value>.+?)\]?\s*(?:\n|$)")
_ANSWER_RE = re.compile(
    r"[\"“”]?\s*答案[\"“”]?\s*[：:](?P<value>.*?)(?=\n\s*(?:来源部门[：:]|==##(?:关键字|相似问(?:法)?)[：:])|\Z)",
    re.S,
)
_DEPARTMENT_RE = re.compile(r"来源部门[：:](?P<value>.+)")
_OPERATION_TITLE_RE = re.compile(r"^(?P<title>.+?一件事)操作指引\s*$")
_SECTION_HEADING_RE = re.compile(r"^(第[一二三四五六七八九十百0-9]+[章节条]|[一二三四五六七八九十]+、|\d+[.．、]|0\d)")
_SOFT_BREAK_RE = re.compile(r"(?<=[。！？；;])")
_URL_RE = re.compile(r"https?://[^\s>*）)】]+", re.IGNORECASE)
_BULLET_RE = re.compile(r"^(?:\d{1,3}[.．、]\s*|[①②③④⑤⑥⑦⑧⑨⑩]\s*|（\d{1,3}）\s*|\(\d{1,3}\)\s*)")
_GUIDE_SECTION_LABELS = {
    "涉及事项": "related_services",
    "办理须知": "process",
    "办理流程": "process",
    "申请材料": "materials",
    "办理材料": "materials",
    "材料清单": "materials",
    "办理条件": "conditions",
    "适用对象": "conditions",
    "服务对象": "conditions",
    "备注": "notes",
}
_OPERATION_SECTION_LABELS = {
    "系统入口": "operation_entry",
    "申报流程": "operation_steps",
    "办理流程": "operation_steps",
    "操作流程": "operation_steps",
    "材料上传": "operation_material_upload",
    "附件上传": "operation_material_upload",
    "办件查询": "operation_query",
    "进度查询": "operation_query",
    "备注": "operation_notes",
}

_SERVICE_ITEMS_SECTION = "01政务服务事项知识"
_ONE_THING_SECTION = "02高效办成一件事"
_COMMON_QA_SECTION = "03常州市常见问题"
_TOPIC_QA_SECTION = "04专题常见问答"
_DEPARTMENT_SECTION = "05业务部门常见问题"
_DISTRICT_QA_SECTION = "06各区常见问题"
_PLUGIN_KIND = "changzhou_gov_service_knowledge_v1"
_SOURCE_DEPARTMENT_MAX = 300


def _source(meta: dict[str, Any]) -> str:
    user_meta = meta.get("user") if isinstance(meta.get("user"), dict) else {}
    for key in ("source", "source_path", "filename", "file_name", "source_file"):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    value = str(user_meta.get("source_rel_path") or "").strip() if isinstance(user_meta, dict) else ""
    if value:
        return value
    return ""


def _source_parts(source: str) -> list[str]:
    return [part for part in Path(source).parts if part not in {"/", ""}]


def _knowledge_section(source: str) -> str:
    for part in _source_parts(source):
        if re.match(r"^\d{2}[^0-9]", part):
            return part
    return ""


def _department_domain(source: str) -> str:
    parts = _source_parts(source)
    for index, part in enumerate(parts):
        if part == _DEPARTMENT_SECTION and index + 1 < len(parts):
            candidate = parts[index + 1]
            return "" if Path(candidate).suffix else candidate
    return ""


def _district_from_source(source: str, section: str) -> str:
    name = Path(source).name.strip()
    for suffix in ("事项清单.txt", "事项清单", "12345QA.txt", "12345QA"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    if section == _DISTRICT_QA_SECTION:
        return name.rsplit(".", 1)[0]
    return ""


def _source_topic(source: str, section: str) -> str:
    if section not in {_COMMON_QA_SECTION, _TOPIC_QA_SECTION, _DEPARTMENT_SECTION, _DISTRICT_QA_SECTION}:
        return ""
    return _clamp_meta_text(Path(source).stem.strip(), 500)


def _clean_marker_value(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^==##(?:(?:关键字|关键词)|相似问(?:法)?)[：:]\s*", "", value)
    value = re.sub(r"##==$", "", value)
    return value.strip().strip("[]")


def _split_list_marker(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[、,，；;]", _clean_marker_value(text)):
        value = _clean_marker_value(part)
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _split_category_path(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in str(text or "").split("/"):
        value = _clean_marker_value(part)
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _case_key(title: str) -> str:
    value = str(title or "").strip()
    value = re.sub(r"[“”\"'‘’\s·\-_/（）()【】\[\]]+", "", value)
    return value or str(title or "").strip()


def _extract_urls(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.finditer(text or ""):
        url = match.group(0).strip().rstrip("。；;，,")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _section_heading_type(line: str, labels: dict[str, str]) -> tuple[str, str] | None:
    text = str(line or "").strip()
    if not text:
        return None
    cleaned = re.sub(r"^[一二三四五六七八九十百0-9]+[、.．]\s*", "", text).strip()
    cleaned = cleaned.rstrip("：:")
    for label, section_type in labels.items():
        if cleaned == label or cleaned.startswith(label):
            return section_type, label
    return None


def _split_named_sections(text: str, labels: dict[str, str]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current_type = "overview"
    current_label = "概览"
    current_lines: list[str] = []

    def flush() -> None:
        content = "\n".join(line for line in current_lines if line.strip()).strip()
        if content:
            sections.append({"section_type": current_type, "label": current_label, "content": content})

    for raw in str(text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = _section_heading_type(line, labels)
        if heading:
            flush()
            current_type, current_label = heading
            current_lines = []
            continue
        if _TITLE_BRACKET_RE.match(line) or line.startswith(("一件事：", "一件事操作指引：")):
            continue
        current_lines.append(line)
    flush()
    return sections


def _material_items(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    material_terms = ("材料", "身份证", "户口", "申请表", "承诺书", "证明", "照片", "证照", "凭证", "学生证", "驾驶证")
    for raw in str(text or "").splitlines():
        line = _BULLET_RE.sub("", raw.strip()).strip()
        if not line or line in {"通用材料", "专项材料", "申请材料", "办理材料"}:
            continue
        if (
            len(line) <= 30
            and line.endswith(("办理", "补贴", "申请", "认定", "登记", "换领", "补办", "注销", "帮扶"))
            and not any(term in line for term in material_terms)
        ):
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(_clamp_meta_text(line, 200))
    return out


def _numbered_steps(text: str) -> list[str]:
    steps: list[str] = []
    seen: set[str] = set()
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not re.match(r"^\d{1,3}[.．、]\s*", line):
            continue
        item = _BULLET_RE.sub("", line).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        steps.append(_clamp_meta_text(item, 260))
    return steps


def _non_step_url_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or not _extract_urls(line):
            continue
        if re.match(r"^\d{1,3}[.．、]\s*", line) and "微课堂" not in line and "手册" not in line:
            continue
        lines.append(line)
    return lines


def _clean_text(text: str) -> str:
    lines: list[str] = []
    for raw in str(text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _ALIAS_RE.fullmatch(line) or _KEYWORD_RE.fullmatch(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _clamp_meta_text(text: str, max_chars: int) -> str:
    value = str(text or "").strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip()


def _split_blocks(text: str) -> list[str]:
    blocks = [part.strip() for part in _BLOCK_SEPARATOR_RE.split(text or "") if part.strip()]
    return blocks or ([str(text or "").strip()] if str(text or "").strip() else [])


def _first_line(text: str) -> str:
    for line in str(text or "").splitlines():
        value = line.strip()
        if value:
            return value
    return ""


def _strip_bracket_title(line: str) -> str:
    match = _TITLE_BRACKET_RE.match(line.strip())
    return (match.group("title") if match else line).strip()


def _long_text_title(text: str) -> str:
    title_lines: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            if title_lines:
                break
            continue
        if title_lines and (line.startswith(("（", "(")) or _SECTION_HEADING_RE.match(line) or line.endswith(("：", ":"))):
            break
        title_lines.append(_strip_bracket_title(line))
        if len("".join(title_lines)) >= 120 or len(title_lines) >= 4:
            break
    return "".join(title_lines).strip() or _strip_bracket_title(_first_line(text))


def _doc_id(source: str, kind: str, index: int, title: str, text: str) -> str:
    seed = f"{source}\n{kind}\n{index}\n{title}\n{text}".encode("utf-8", "ignore")
    return hashlib.sha256(seed).hexdigest()[:24]


def _common_meta(source_doc: Document, *, kind: str, title: str, index: int, text: str) -> dict[str, Any]:
    meta = dict(source_doc.metadata or {})
    source = _source(meta)
    section = _knowledge_section(source)
    meta.update(
        {
            "gov_knowledge_plugin": _PLUGIN_KIND,
            "gov_knowledge_type": kind,
            "knowledge_root": "20260522政务服务智能客服知识",
            "knowledge_section": section,
            "source_file": source,
            "source_record_index": index,
            "source_record_id": _doc_id(source, kind, index, title, text),
        }
    )
    district = _district_from_source(source, section)
    if district:
        meta["district"] = district
    department = _department_domain(source)
    if department:
        meta["department_domain"] = department
    topic = _source_topic(source, section)
    if topic:
        meta["source_topic"] = topic
    return meta


def _augment_service_item_meta(doc: Document) -> Document:
    meta = dict(doc.metadata or {})
    source = _source(meta)
    meta.update(
        {
            "gov_knowledge_plugin": _PLUGIN_KIND,
            "gov_knowledge_type": "service_item",
            "knowledge_root": "20260522政务服务智能客服知识",
            "knowledge_section": _SERVICE_ITEMS_SECTION,
            "source_file": source,
        }
    )
    doc.metadata = meta
    return doc


def _govern_one_thing_guide(source_doc: Document) -> list[Document]:
    out: list[Document] = []
    for index, block in enumerate(_split_blocks(source_doc.page_content or ""), 1):
        title = _strip_bracket_title(_first_line(block))
        keywords_match = _KEYWORD_RE.search(block)
        keywords = _split_list_marker(keywords_match.group("value")) if keywords_match else []
        text = _clean_text(block)
        meta = _common_meta(source_doc, kind="one_thing_guide", title=title, index=index, text=text)
        meta["case_title"] = title
        meta["case_key"] = _case_key(title)
        meta["keywords"] = keywords
        sections = _split_named_sections(text, _GUIDE_SECTION_LABELS)
        related = next((s["content"] for s in sections if s.get("section_type") == "related_services"), "")
        materials = "\n".join(str(s.get("content") or "") for s in sections if s.get("section_type") == "materials")
        meta["related_services"] = _split_list_marker(related)
        meta["materials"] = _material_items(materials)
        meta["urls"] = _extract_urls(text)
        out.append(Document(page_content=f"一件事：{title}\n{text}".strip(), metadata=meta))
    return out


def _split_operation_blocks(text: str) -> list[str]:
    blocks = _split_blocks(text)
    if len(blocks) > 1:
        return blocks
    indices: list[int] = []
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    cursor = 0
    for line in normalized.splitlines(keepends=True):
        if _OPERATION_TITLE_RE.match(line.strip()):
            indices.append(cursor)
        cursor += len(line)
    if len(indices) <= 1:
        return blocks
    indices.append(len(normalized))
    return [normalized[indices[i] : indices[i + 1]].strip() for i in range(len(indices) - 1) if normalized[indices[i] : indices[i + 1]].strip()]


def _govern_one_thing_operation(source_doc: Document) -> list[Document]:
    out: list[Document] = []
    for index, block in enumerate(_split_operation_blocks(source_doc.page_content or ""), 1):
        first = _first_line(block)
        match = _OPERATION_TITLE_RE.match(first)
        title = (match.group("title") if match else first.replace("操作指引", "")).strip()
        text = _clean_text(block)
        meta = _common_meta(source_doc, kind="one_thing_operation", title=title, index=index, text=text)
        meta["case_title"] = title
        meta["case_key"] = _case_key(title)
        sections = _split_named_sections(text, _OPERATION_SECTION_LABELS)
        meta["operation_steps"] = [
            step
            for section in sections
            if section.get("section_type") in {"operation_steps", "operation_material_upload", "operation_query"}
            for step in _numbered_steps(str(section.get("content") or ""))
        ]
        meta["urls"] = _extract_urls(text)
        out.append(Document(page_content=f"一件事操作指引：{title}\n{text}".strip(), metadata=meta))
    return out


def _clean_question(value: str) -> str:
    return str(value or "").strip().strip("[]").rstrip("]").strip()


def _build_qa_document(
    source_doc: Document,
    *,
    index: int,
    question: str,
    answer: str,
    aliases: list[str] | None = None,
    keywords: list[str] | None = None,
    source_department: str = "",
    source_sheet: str = "",
    category_path: list[str] | None = None,
    applicable_area: str = "",
    service_url: str = "",
) -> Document | None:
    question = _clean_question(question)
    answer = _clean_text(answer)
    if not question or not answer:
        return None
    aliases = list(aliases or [])
    keywords = list(keywords or [])
    category_path = [item for item in list(category_path or []) if str(item).strip()]
    category_leaf = category_path[-1] if category_path else ""
    source_department = _clamp_meta_text(source_department, _SOURCE_DEPARTMENT_MAX)
    applicable_area = _clamp_meta_text(applicable_area, 200)
    service_url = _extract_urls(service_url)[0] if _extract_urls(service_url) else str(service_url or "").strip()
    lines = [f"问题：{question}"]
    if category_path:
        lines.append(f"业务分类：{'/'.join(category_path)}")
    if keywords:
        lines.append(f"关键字：{'、'.join(keywords)}")
    if aliases:
        lines.append(f"相似问法：{'、'.join(aliases)}")
    if applicable_area:
        lines.append(f"适用区域：{applicable_area}")
    if service_url:
        lines.append(f"办事链接：{service_url}")
    lines.append(f"答案：{answer}")
    if source_department:
        lines.append(f"来源部门：{source_department}")
    if source_sheet:
        lines.append(f"来源工作表：{source_sheet}")
    text = "\n".join(lines)
    meta = _common_meta(source_doc, kind="qa", title=question, index=index, text=text)
    meta["question"] = question
    meta["answer"] = answer
    meta["aliases"] = aliases
    meta["keywords"] = keywords
    urls: list[str] = []
    seen_urls: set[str] = set()
    for url in [*_extract_urls(answer), *_extract_urls(service_url)]:
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        urls.append(url)
    meta["urls"] = urls
    meta["source_department"] = source_department
    if source_sheet:
        meta["source_sheet"] = _clamp_meta_text(source_sheet, 200)
    if category_path:
        meta["category_path"] = [_clamp_meta_text(item, 200) for item in category_path]
        meta["category_leaf"] = _clamp_meta_text(category_leaf, 200)
    if applicable_area:
        meta["applicable_area"] = applicable_area
    if service_url:
        meta["service_url"] = _clamp_meta_text(service_url, 1000)
    return Document(page_content=text, metadata=meta)


def _govern_qa(source_doc: Document) -> list[Document]:
    out: list[Document] = []
    for index, block in enumerate(_split_blocks(source_doc.page_content or ""), 1):
        question_match = _QUESTION_RE.search(block)
        answer_match = _ANSWER_RE.search(block)
        if not question_match or not answer_match:
            continue
        dept_match = _DEPARTMENT_RE.search(block)
        aliases_match = _ALIAS_RE.search(block)
        keywords_match = _KEYWORD_RE.search(block)
        doc = _build_qa_document(
            source_doc,
            index=index,
            question=question_match.group("value"),
            answer=answer_match.group("value"),
            aliases=_split_list_marker(aliases_match.group("value")) if aliases_match else [],
            keywords=_split_list_marker(keywords_match.group("value")) if keywords_match else [],
            source_department=dept_match.group("value") if dept_match else "",
        )
        if doc is not None:
            out.append(doc)
    return out


def _markdown_cells(line: str) -> list[str]:
    stripped = str(line or "").strip()
    if not stripped.startswith("|"):
        return []
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.lstrip("|").split("|")]


def _is_markdown_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells if cell.strip())


def _header_key(cell: str) -> str:
    value = _clean_marker_value(cell)
    value = re.sub(r"[\s\[\]（）()【】:：]+", "", value)
    if "问答标题" in value or "问题" in value:
        return "question"
    if "问答答案" in value or "答案" in value:
        return "answer"
    if "相似问" in value:
        return "aliases"
    if "关键字" in value or "关键词" in value:
        return "keywords"
    if "问答提供部门" in value or "来源部门" in value:
        return "source_department"
    if "类目路径" in value or "分类路径" in value or "业务分类" in value:
        return "category_path"
    if "适用区域" in value or "适用地区" in value:
        return "applicable_area"
    if "办事链接" in value or "办理链接" in value or "服务链接" in value:
        return "service_url"
    return ""


def _parse_markdown_qa_table(source_doc: Document, lines: list[str], sheet: str, start_index: int) -> list[Document]:
    if len(lines) < 2:
        return []
    header_index = -1
    keys: list[str] = []
    for index, raw in enumerate(lines):
        candidate_keys = [_header_key(cell) for cell in _markdown_cells(raw)]
        if "question" in candidate_keys and "answer" in candidate_keys:
            header_index = index
            keys = candidate_keys
            break
    if header_index < 0:
        return []
    if "question" not in keys or "answer" not in keys:
        return []
    data_lines = lines[header_index + 1 :]
    if data_lines and _is_markdown_separator(_markdown_cells(data_lines[0])):
        data_lines = data_lines[1:]
    out: list[Document] = []
    for raw in data_lines:
        cells = _markdown_cells(raw)
        if not cells:
            continue
        values = {key: cells[index] for index, key in enumerate(keys) if key and index < len(cells)}
        doc = _build_qa_document(
            source_doc,
            index=start_index + len(out),
            question=values.get("question", ""),
            answer=values.get("answer", ""),
            aliases=_split_list_marker(values.get("aliases", "")),
            keywords=_split_list_marker(values.get("keywords", "")),
            source_department=values.get("source_department", ""),
            source_sheet=sheet,
            category_path=_split_category_path(values.get("category_path", "")),
            applicable_area=values.get("applicable_area", ""),
            service_url=values.get("service_url", ""),
        )
        if doc is not None:
            out.append(doc)
    return out


def _govern_markdown_table_qa(source_doc: Document) -> list[Document]:
    out: list[Document] = []
    current_sheet = ""
    table_lines: list[str] = []

    def flush() -> None:
        nonlocal table_lines
        if table_lines:
            out.extend(_parse_markdown_qa_table(source_doc, table_lines, current_sheet, len(out) + 1))
            table_lines = []

    for raw in str(source_doc.page_content or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw.strip()
        sheet_match = re.match(r"^#{1,6}\s*Sheet[：:]\s*(?P<sheet>.+?)\s*$", line, re.I)
        if sheet_match:
            flush()
            current_sheet = _clamp_meta_text(sheet_match.group("sheet"), 200)
            continue
        if line.startswith("|"):
            table_lines.append(line)
            continue
        flush()
    flush()
    return out


def _is_answer_marker(line: str) -> bool:
    return bool(re.match(r"^答\s*[：:]", str(line or "").strip()))


def _strip_answer_marker(line: str) -> str:
    return re.sub(r"^答\s*[：:]\s*", "", str(line or "").strip()).strip()


def _is_loose_qa_heading(line: str) -> bool:
    text = str(line or "").strip()
    if not text or _is_answer_marker(text) or len(text) > 40:
        return False
    if text.startswith(("Excel:", "Sheets:", "##", "|", "==")):
        return False
    if re.search(r"[。！？?；;:：]", text):
        return False
    return True


def _previous_non_empty_index(lines: list[str], start: int) -> int:
    for index in range(start, -1, -1):
        if str(lines[index] or "").strip():
            return index
    return -1


def _loose_qa_category(lines: list[str], question_index: int, topic: str) -> list[str]:
    for index in range(question_index - 1, -1, -1):
        line = lines[index].strip()
        if _is_loose_qa_heading(line):
            return [topic, line] if topic else [line]
    return [topic] if topic else []


def _govern_loose_answer_marker_qa(source_doc: Document) -> list[Document]:
    lines = [line.strip() for line in str(source_doc.page_content or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()]
    answer_indices = [index for index, line in enumerate(lines) if _is_answer_marker(line)]
    if not answer_indices:
        return []
    topic = _source_topic(_source(dict(source_doc.metadata or {})), _knowledge_section(_source(dict(source_doc.metadata or {}))))
    out: list[Document] = []
    for pair_index, answer_index in enumerate(answer_indices):
        question_index = _previous_non_empty_index(lines, answer_index - 1)
        if question_index < 0:
            continue
        next_answer_index = answer_indices[pair_index + 1] if pair_index + 1 < len(answer_indices) else len(lines)
        next_question_index = _previous_non_empty_index(lines, next_answer_index - 1) if pair_index + 1 < len(answer_indices) else len(lines)
        answer_lines = [_strip_answer_marker(lines[answer_index])]
        answer_lines.extend(line for line in lines[answer_index + 1 : next_question_index] if line.strip())
        doc = _build_qa_document(
            source_doc,
            index=len(out) + 1,
            question=lines[question_index],
            answer="\n".join(answer_lines),
            category_path=_loose_qa_category(lines, question_index, topic),
        )
        if doc is not None:
            out.append(doc)
    return out


def _govern_long_text(source_doc: Document) -> list[Document]:
    out: list[Document] = []
    source = _source(dict(source_doc.metadata or {}))
    kind = "regulation_text" if "法规" in source or "不动产" in source else "gov_text"
    for index, block in enumerate(_split_blocks(source_doc.page_content or ""), 1):
        text = _clean_text(block)
        if not text:
            continue
        title = _long_text_title(text)
        meta = _common_meta(source_doc, kind=kind, title=title, index=index, text=text)
        meta["title"] = title
        out.append(Document(page_content=text, metadata=meta))
    return out


def govern_documents(
    documents: list[Document],
    params: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> list[Document]:
    out: list[Document] = []
    for doc in documents or []:
        meta = dict(doc.metadata or {})
        source = _source(meta)
        section = _knowledge_section(source)
        text = doc.page_content or ""
        if section == _SERVICE_ITEMS_SECTION or "[事项名称：" in text:
            out.extend(_augment_service_item_meta(item) for item in _govern_service_items([doc], params=params, context=context))
        elif section == _ONE_THING_SECTION and "操作指引" in Path(source).name:
            out.extend(_govern_one_thing_operation(doc))
        elif section == _ONE_THING_SECTION:
            out.extend(_govern_one_thing_guide(doc))
        else:
            qa_records = _govern_qa(doc)
            if not qa_records:
                qa_records = _govern_markdown_table_qa(doc)
            if not qa_records:
                qa_records = _govern_loose_answer_marker_qa(doc)
            out.extend(qa_records or _govern_long_text(doc))
    return out


def _split_for_chunk(text: str, max_chars: int) -> list[str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    def split_long_line(line: str) -> list[str]:
        value = str(line or "").strip()
        if len(value) <= max_chars:
            return [value] if value else []
        pieces: list[str] = []
        current = ""
        for part in [p.strip() for p in _SOFT_BREAK_RE.split(value) if p.strip()]:
            if len(part) > max_chars:
                if current:
                    pieces.append(current.strip())
                    current = ""
                pieces.extend(part[i : i + max_chars].strip() for i in range(0, len(part), max_chars) if part[i : i + max_chars].strip())
                continue
            if current and len(current) + len(part) + 1 > max_chars:
                pieces.append(current.strip())
                current = part
            else:
                current = f"{current}{part}" if current else part
        if current:
            pieces.append(current.strip())
        return pieces

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for raw in cleaned.splitlines():
        line = raw.strip()
        if not line:
            continue
        starts_new_section = bool(_SECTION_HEADING_RE.match(line))
        for piece in split_long_line(line):
            if current and (current_len + len(piece) + 1 > max_chars or (starts_new_section and current_len > max_chars * 0.45)):
                chunks.append("\n".join(current).strip())
                current = []
                current_len = 0
            current.append(piece)
            current_len += len(piece) + 1
    if current:
        chunks.append("\n".join(current).strip())
    return chunks or [cleaned[:max_chars]]


def _chunk_kind(kind: str) -> str:
    return {
        "qa": "qa_pair",
        "one_thing_guide": "one_thing_guide",
        "one_thing_operation": "one_thing_operation",
        "regulation_text": "regulation_section",
        "gov_text": "gov_text_section",
    }.get(kind, "gov_text_section")


def _one_thing_chunk_content(*, case_title: str, label: str, content: str) -> str:
    lines = [f"一件事：{case_title}"]
    if label:
        lines.append(f"章节：{label}")
    lines.append(str(content or "").strip())
    return "\n".join(line for line in lines if line).strip()


def _one_thing_chunk_meta(
    source_meta: dict[str, Any],
    *,
    section_type: str,
    label: str,
    chunk_index: int,
    content: str,
    local_index: int,
    local_total: int,
) -> dict[str, Any]:
    meta = dict(source_meta)
    meta["case_key"] = str(meta.get("case_key") or _case_key(str(meta.get("case_title") or ""))).strip()
    meta["section_type"] = section_type
    meta["section_label"] = label
    meta["chunk_strategy"] = _PLUGIN_KIND
    meta["chunk_kind"] = f"one_thing_{section_type}"
    meta["chunk_index"] = chunk_index
    meta["source_chunk_index"] = local_index
    if local_total > 1:
        meta["chunk_part_index"] = local_index
        meta["chunk_part_total"] = local_total

    if section_type == "related_services":
        meta["related_services"] = _split_list_marker(content)
    elif section_type == "materials":
        meta["materials"] = _material_items(content)
    elif section_type in {"operation_steps", "operation_material_upload", "operation_query"}:
        steps = _numbered_steps(content)
        meta["operation_steps"] = steps
        if steps:
            meta["step_no"] = 1

    urls = _extract_urls(content)
    if urls:
        meta["urls"] = urls
    return meta


def _emit_one_thing_section_chunks(
    *,
    source_meta: dict[str, Any],
    case_title: str,
    sections: list[dict[str, Any]],
    max_chars: int,
    start_index: int,
) -> list[Document]:
    chunks: list[Document] = []
    for section in sections:
        section_type = str(section.get("section_type") or "").strip()
        label = str(section.get("label") or "").strip()
        content = str(section.get("content") or "").strip()
        if not section_type or not content:
            continue
        rendered = _one_thing_chunk_content(case_title=case_title, label=label, content=content)
        parts = _split_for_chunk(rendered, max_chars)
        for local_index, part in enumerate(parts, 1):
            meta = _one_thing_chunk_meta(
                source_meta,
                section_type=section_type,
                label=label,
                chunk_index=start_index + len(chunks),
                content=content if len(parts) == 1 else part,
                local_index=local_index,
                local_total=len(parts),
            )
            chunks.append(Document(page_content=part, metadata=meta))
    return chunks


def _chunk_one_thing_guide(doc: Document, *, max_chars: int, start_index: int) -> list[Document]:
    meta = dict(doc.metadata or {})
    case_title = str(meta.get("case_title") or "").strip() or _first_line(doc.page_content or "")
    sections = _split_named_sections(doc.page_content or "", _GUIDE_SECTION_LABELS)
    sections = [s for s in sections if s.get("section_type") != "overview"] or sections
    return _emit_one_thing_section_chunks(
        source_meta=meta,
        case_title=case_title,
        sections=sections,
        max_chars=max_chars,
        start_index=start_index,
    )


def _chunk_one_thing_operation(doc: Document, *, max_chars: int, start_index: int) -> list[Document]:
    meta = dict(doc.metadata or {})
    case_title = str(meta.get("case_title") or "").strip() or _first_line(doc.page_content or "")
    sections = _split_named_sections(doc.page_content or "", _OPERATION_SECTION_LABELS)
    url_lines: list[str] = []
    for section in sections:
        url_lines.extend(_non_step_url_lines(str(section.get("content") or "")))
    if url_lines:
        sections.append(
            {
                "section_type": "operation_url",
                "label": "在线入口",
                "content": "\n".join(dict.fromkeys(url_lines)),
            }
        )
    sections = [s for s in sections if s.get("section_type") != "overview"] or sections
    return _emit_one_thing_section_chunks(
        source_meta=meta,
        case_title=case_title,
        sections=sections,
        max_chars=max_chars,
        start_index=start_index,
    )


def _chunk_generic(documents: list[Document], *, max_chars: int) -> list[Document]:
    chunks: list[Document] = []
    for source_doc in documents:
        meta = dict(source_doc.metadata or {})
        kind = str(meta.get("gov_knowledge_type") or "gov_text")
        if kind == "one_thing_guide":
            chunks.extend(_chunk_one_thing_guide(source_doc, max_chars=max_chars, start_index=len(chunks)))
            continue
        if kind == "one_thing_operation":
            chunks.extend(_chunk_one_thing_operation(source_doc, max_chars=max_chars, start_index=len(chunks)))
            continue
        for local_index, content in enumerate(_split_for_chunk(source_doc.page_content or "", max_chars), 1):
            chunk_meta = dict(meta)
            chunk_meta.update(
                {
                    "chunk_strategy": _PLUGIN_KIND,
                    "chunk_kind": _chunk_kind(kind),
                    "chunk_index": len(chunks),
                    "source_chunk_index": local_index,
                }
            )
            chunks.append(Document(page_content=content, metadata=chunk_meta))
    return chunks


def chunk_documents(
    documents: list[Document],
    params: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> list[Document]:
    params = dict(params or {})
    max_chars = int(params.get("max_record_chars") or params.get("max_chars") or 1600)
    governed = list(documents or [])
    if governed and not any((doc.metadata or {}).get("gov_knowledge_type") for doc in governed):
        governed = govern_documents(governed, params=params, context=context)

    service_items = [doc for doc in governed if (doc.metadata or {}).get("gov_knowledge_type") == "service_item"]
    others = [doc for doc in governed if (doc.metadata or {}).get("gov_knowledge_type") != "service_item"]
    chunks: list[Document] = []
    if service_items:
        chunks.extend(_chunk_service_items(service_items, params={**params, "max_record_chars": max_chars}, context=context))
    chunks.extend(_chunk_generic(others, max_chars=max_chars))
    for index, chunk in enumerate(chunks):
        meta = dict(chunk.metadata or {})
        meta.setdefault("chunk_strategy", _PLUGIN_KIND)
        meta["chunk_index"] = index
        meta.setdefault("gov_knowledge_plugin", _PLUGIN_KIND)
        chunk.metadata = meta
    return chunks
