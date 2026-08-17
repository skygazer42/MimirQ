"""Governance and chunk helpers owned by the Changzhou service plugin."""

import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from langchain_core.documents import Document

_ITEM_SEPARATOR = "==##########=="
_TITLE_RE = re.compile(r"^\[事项名称：(?P<title>.+?)\]\s*$", re.MULTILINE)
_FIELD_RE = re.compile(r"^(?P<name>[\u4e00-\u9fffA-Za-z0-9（）()·、/\-]{2,32})[：:](?P<value>.*)$")
_ALIAS_RE = re.compile(r"==##相似问法：(?P<aliases>.+?)##==")
_URL_RE = re.compile(r"https?://[^\s>*）)】]+", re.IGNORECASE)
_NUMBERED_ITEM_BOUNDARY_RE = re.compile(r"\s+(?=\d{1,3}[、.．])")
_PAREN_TERM_RE = re.compile(r"[（(](?P<value>[^）)]{1,80})[）)]")
_TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
}

_PRIMARY_FIELDS = (
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

_CHUNK_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "service_basic",
        ("行使层级", "办理形式", "办理地点", "办理时间", "办件类型", "法定办结时限", "承诺办结时限", "收费情况"),
    ),
    ("service_condition", ("受理条件",)),
    ("service_materials", ("办理材料", "精细化材料提醒")),
    ("service_process", ("办理流程",)),
    ("service_contact", ("咨询方式", "监督投诉方式", "在线办理地址")),
)
_SERVICE_RETRIEVAL_INTENTS = (
    "需要什么材料",
    "在哪里办理",
    "咨询电话是多少",
    "能不能网上办",
    "怎么办理",
)


def _source_name(meta: dict[str, Any]) -> str:
    user_meta = meta.get("user") if isinstance(meta.get("user"), dict) else {}
    for key in ("source", "source_path", "filename", "file_name", "source_file"):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    value = str(user_meta.get("source_rel_path") or "").strip() if isinstance(user_meta, dict) else ""
    if value:
        return value
    return ""


def _district_from_source(source: str) -> str:
    name = source.rsplit("/", 1)[-1].strip()
    if name.endswith("事项清单.txt"):
        return name[: -len("事项清单.txt")]
    if name.endswith("事项清单"):
        return name[: -len("事项清单")]
    return name.rsplit(".", 1)[0] if "." in name else name


def _normalize_url(raw: str) -> str:
    value = str(raw or "").strip().strip("<>").strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        query = [
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _TRACKING_QUERY_KEYS
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    except ValueError:
        return value


def _extract_url(text: str) -> tuple[str, str]:
    match = _URL_RE.search(text or "")
    if not match:
        return "", ""
    raw = match.group(0).strip()
    return raw, _normalize_url(raw)


def _split_aliases(text: str) -> list[str]:
    match = _ALIAS_RE.search(text or "")
    if not match:
        return []
    seen: set[str] = set()
    aliases: list[str] = []
    for part in re.split(r"[、,，；;]", match.group("aliases")):
        alias = part.strip()
        if not alias or alias in seen:
            continue
        seen.add(alias)
        aliases.append(alias)
    return aliases


def _semantic_terms(*values: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip().strip("[]").strip()
        candidates = [text, *[match.group("value").strip() for match in _PAREN_TERM_RE.finditer(text)]]
        for candidate in candidates:
            term = str(candidate or "").strip().strip("？?。；;，,")
            if not term or term in seen:
                continue
            seen.add(term)
            out.append(term)
    return out


def _service_semantic_keys(*, district: str, title: str, aliases: list[str]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()

    def add(key: str) -> None:
        value = str(key or "").strip()
        if not value or value in seen:
            return
        seen.add(value)
        keys.append(value)

    title = str(title or "").strip()
    district = str(district or "").strip()
    if title:
        if district:
            add(f"service:{district}:{title}")
        add(f"service:{title}")
    for term in _semantic_terms(title, *aliases):
        add(f"intent:{term}")
    for term in _semantic_terms(*aliases):
        add(f"alias:{term}")
    return keys


def _clean_block_text(block: str) -> str:
    lines: list[str] = []
    for raw in (block or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if _ALIAS_RE.fullmatch(line):
            continue
        if line.startswith("在线办理地址"):
            raw_url, normalized_url = _extract_url(line)
            if normalized_url:
                line = f"在线办理地址：{normalized_url}"
            elif raw_url:
                line = f"在线办理地址：{raw_url}"
        lines.append(line)
    return "\n".join(lines)


def _extract_fields(cleaned: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_name = ""
    current_value: list[str] = []
    for raw in (cleaned or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _TITLE_RE.fullmatch(line):
            continue
        match = _FIELD_RE.match(line)
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
    return fields


def _render_record_text(*, district: str, title: str, fields: dict[str, str], aliases: list[str]) -> str:
    lines = [f"区县：{district}", f"事项名称：{title}"]
    if aliases:
        lines.append(f"相似问法：{'、'.join(aliases)}")
    for name in _PRIMARY_FIELDS:
        value = fields.get(name)
        if value:
            lines.append(f"{name}：{value}")
    for name, value in fields.items():
        if name not in _PRIMARY_FIELDS and value:
            lines.append(f"{name}：{value}")
    return "\n".join(lines).strip()


def _identity_text(value: str) -> str:
    text = str(value or "").strip().translate(str.maketrans({"（": "(", "）": ")"}))
    return re.sub(r"\s+", "", text)


def _record_id(
    *,
    source: str,
    district: str,
    title: str,
    content_fingerprint: str = "",
    duplicate_variant_count: int = 1,
) -> str:
    # Service-item retrieval is question-oriented for normal rows, but same-title
    # rows with different facts must not collapse during evidence de-duplication.
    seed = f"{source}\n{district}\n{_identity_text(title)}".encode("utf-8", "ignore")
    base = hashlib.sha256(seed).hexdigest()[:24]
    if duplicate_variant_count <= 1:
        return base
    suffix = str(content_fingerprint or "").strip()[:12]
    return f"{base}-{suffix}" if suffix else base


def _block_positions(text: str) -> list[tuple[int, int, str]]:
    positions: list[tuple[int, int, str]] = []
    cursor = 0
    sep_len = len(_ITEM_SEPARATOR)
    for raw in text.split(_ITEM_SEPARATOR):
        start = cursor
        end = start + len(raw)
        cursor = end + sep_len
        block = raw.strip()
        if not block:
            continue
        left_trim = len(raw) - len(raw.lstrip())
        right_trim = len(raw.rstrip())
        positions.append((start + left_trim, start + right_trim, block))
    return positions


def govern_documents(
    documents: list[Document],
    params: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> list[Document]:
    out: list[Document] = []
    params = dict(params or {})
    default_dataset_type = str(params.get("dataset_type") or "gov_service_item")
    for source_doc in documents or []:
        source_meta = dict(source_doc.metadata or {})
        source = _source_name(source_meta)
        district = str(params.get("district") or source_meta.get("district") or _district_from_source(source)).strip()
        text = source_doc.page_content or ""
        candidates: list[dict[str, Any]] = []

        for idx, (start, end, block) in enumerate(_block_positions(text), 1):
            title_match = _TITLE_RE.search(block)
            if not title_match:
                continue
            title = title_match.group("title").strip()
            aliases = _split_aliases(block)
            cleaned = _clean_block_text(block)
            fields = _extract_fields(cleaned)
            raw_url = fields.get("在线办理地址", "")
            online_url_raw, online_url_normalized = _extract_url(raw_url)
            if online_url_normalized:
                fields["在线办理地址"] = online_url_normalized
            record_text = _render_record_text(district=district, title=title, fields=fields, aliases=aliases)
            content_fingerprint = hashlib.sha256(record_text.encode("utf-8", "ignore")).hexdigest()[:12]
            identity_key = f"{source}\n{district}\n{_identity_text(title)}"
            candidates.append(
                {
                    "idx": idx,
                    "start": start,
                    "end": end,
                    "title": title,
                    "aliases": aliases,
                    "fields": fields,
                    "record_text": record_text,
                    "content_fingerprint": content_fingerprint,
                    "identity_key": identity_key,
                    "online_url_raw": online_url_raw,
                    "online_url_normalized": online_url_normalized,
                }
            )

        variants_by_key: dict[str, set[str]] = {}
        for item in candidates:
            variants_by_key.setdefault(str(item["identity_key"]), set()).add(str(item["content_fingerprint"]))
        variant_counts = {key: len(values) for key, values in variants_by_key.items()}

        for item in candidates:
            title = str(item["title"])
            aliases = list(item["aliases"])
            fields = dict(item["fields"])
            record_text = str(item["record_text"])
            online_url_raw = str(item["online_url_raw"])
            online_url_normalized = str(item["online_url_normalized"])
            record_id = _record_id(
                source=source,
                district=district,
                title=title,
                content_fingerprint=str(item["content_fingerprint"]),
                duplicate_variant_count=variant_counts.get(str(item["identity_key"]), 1),
            )
            meta = {
                **source_meta,
                "dataset_type": default_dataset_type,
                "district": district,
                "service_name": title,
                "service_aliases": aliases,
                "source_file": source,
                "source_record_id": record_id,
                "source_record_index": int(item["idx"]),
                "source_start_char": int(item["start"]),
                "source_end_char": int(item["end"]),
                "online_url": online_url_normalized or online_url_raw,
                "online_url_raw": online_url_raw,
                "online_url_normalized": online_url_normalized,
                "service_fields": fields,
                "semantic_keys": _service_semantic_keys(district=district, title=title, aliases=aliases),
                "governance_python_plugin_kind": "gov_service_items_v1",
            }
            out.append(Document(page_content=record_text, metadata=meta))
    return out


def _base_chunk_meta(doc: Document, *, chunk_kind: str, chunk_index: int) -> dict[str, Any]:
    meta = dict(doc.metadata or {})
    meta["chunk_kind"] = chunk_kind
    meta["chunk_strategy"] = "gov_service_items_python"
    meta["chunk_index"] = chunk_index
    meta.setdefault("document_type", "gov_service_item")
    return meta


def _with_offsets(doc: Document, meta: dict[str, Any], content: str) -> dict[str, Any]:
    local_start = (doc.page_content or "").find(content)
    if local_start >= 0:
        meta["start_char"] = local_start
        meta["end_char"] = local_start + len(content)
    else:
        meta["start_char"] = 0
        meta["end_char"] = len(doc.page_content or "")
    return meta


def _prefix(doc: Document) -> str:
    meta = dict(doc.metadata or {})
    district = str(meta.get("district") or "").strip()
    title = str(meta.get("service_name") or "").strip()
    aliases = meta.get("service_aliases") if isinstance(meta.get("service_aliases"), list) else []
    lines = []
    if district:
        lines.append(f"区县：{district}")
    if title:
        lines.append(f"事项名称：{title}")
    if aliases:
        lines.append(f"相似问法：{'、'.join(str(a) for a in aliases if str(a).strip())}")
    return "\n".join(lines).strip()


def _service_retrieval_intents(doc: Document) -> list[str]:
    meta = dict(doc.metadata or {})
    title = str(meta.get("service_name") or "").strip()
    if not title:
        return list(_SERVICE_RETRIEVAL_INTENTS)
    district = str(meta.get("district") or "").strip()
    scoped = [f"{district}{title}{intent}" for intent in _SERVICE_RETRIEVAL_INTENTS] if district else []
    generic = [f"{title}{intent}" for intent in _SERVICE_RETRIEVAL_INTENTS]
    return list(dict.fromkeys([*scoped, *generic]))


def _with_service_retrieval_meta(doc: Document, meta: dict[str, Any]) -> dict[str, Any]:
    meta["retrieval_intents"] = _service_retrieval_intents(doc)
    return meta


def _split_value_units(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in _NUMBERED_ITEM_BOUNDARY_RE.split(text) if part.strip()]
    if len(parts) > 1:
        return parts
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines if len(lines) > 1 else [text]


def _split_oversize_unit(unit: str, budget: int) -> list[str]:
    text = str(unit or "").strip()
    if not text:
        return []
    if len(text) <= budget:
        return [text]
    step = max(80, int(budget or 0))
    return [text[i : i + step].strip() for i in range(0, len(text), step) if text[i : i + step].strip()]


def _field_segments(name: str, value: str, *, budget: int) -> list[str]:
    label = f"{name}："
    value_budget = max(80, int(budget or 0) - len(label))
    segments: list[str] = []
    current: list[str] = []
    current_len = 0

    for unit in _split_value_units(value):
        for piece in _split_oversize_unit(unit, value_budget):
            extra = len(piece) + (4 if current else 0)
            if current and current_len + extra > value_budget:
                segments.append(f"{label}{'    '.join(current)}")
                current = []
                current_len = 0
            current.append(piece)
            current_len += extra

    if current:
        segments.append(f"{label}{'    '.join(current)}")
    return segments


def _chunk_contents(prefix: str, fields: dict[str, str], field_names: tuple[str, ...], *, max_chars: int) -> list[str]:
    prefix = str(prefix or "").strip()
    budget = max(120, int(max_chars or 0) - (len(prefix) + 1 if prefix else 0))
    segments: list[str] = []
    for name in field_names:
        value = fields.get(name)
        if value:
            segments.extend(_field_segments(name, value, budget=budget))

    chunks: list[str] = []
    current: list[str] = [prefix] if prefix else []
    current_len = len(prefix) if prefix else 0
    for segment in segments:
        separator_len = 1 if current else 0
        if current and current_len + separator_len + len(segment) > max_chars:
            chunk = "\n".join(current).strip()
            if chunk and chunk != prefix:
                chunks.append(chunk)
            current = [prefix] if prefix else []
            current_len = len(prefix) if prefix else 0
            separator_len = 1 if current else 0
        current.append(segment)
        current_len += separator_len + len(segment)

    chunk = "\n".join(current).strip()
    if chunk and chunk != prefix:
        chunks.append(chunk)
    return chunks


def chunk_documents(
    documents: list[Document],
    params: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> list[Document]:
    params = dict(params or {})
    max_record_chars = int(params.get("max_record_chars") or 1500)
    chunks: list[Document] = []
    chunk_index = 0

    for doc in documents or []:
        text = (doc.page_content or "").strip()
        if not text:
            continue
        meta0 = dict(doc.metadata or {})
        fields = meta0.get("service_fields") if isinstance(meta0.get("service_fields"), dict) else _extract_fields(text)
        title = str(meta0.get("service_name") or "").strip()
        aliases = meta0.get("service_aliases") if isinstance(meta0.get("service_aliases"), list) else []
        district = str(meta0.get("district") or "").strip()
        canonical_text = (
            _render_record_text(district=district, title=title, fields=fields, aliases=aliases)
            if title and fields
            else text
        )
        text_for_chunk = canonical_text or text

        if len(text_for_chunk) <= max_record_chars:
            meta = _base_chunk_meta(doc, chunk_kind="service_item_full", chunk_index=chunk_index)
            meta = _with_offsets(doc, meta, text_for_chunk)
            meta = _with_service_retrieval_meta(doc, meta)
            chunks.append(Document(page_content=text_for_chunk, metadata=meta))
            chunk_index += 1
            continue

        prefix = _prefix(doc)
        emitted = False
        for chunk_kind, field_names in _CHUNK_GROUPS:
            contents = _chunk_contents(prefix, fields, field_names, max_chars=max_record_chars)
            for part_index, content in enumerate(contents, 1):
                meta = _base_chunk_meta(doc, chunk_kind=chunk_kind, chunk_index=chunk_index)
                meta["chunk_fields"] = list(field_names)
                if len(contents) > 1:
                    meta["chunk_part_index"] = part_index
                    meta["chunk_part_total"] = len(contents)
                meta = _with_offsets(doc, meta, content)
                meta = _with_service_retrieval_meta(doc, meta)
                chunks.append(Document(page_content=content, metadata=meta))
                chunk_index += 1
                emitted = True
        if not emitted:
            meta = _base_chunk_meta(doc, chunk_kind="service_item_full", chunk_index=chunk_index)
            meta = _with_offsets(doc, meta, text)
            meta = _with_service_retrieval_meta(doc, meta)
            chunks.append(Document(page_content=text, metadata=meta))
            chunk_index += 1

    return chunks


__all__ = ["chunk_documents", "govern_documents"]
