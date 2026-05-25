from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any

from app.models.document import DocumentChunk
from app.rag.kg.extraction.parser import EntityValueParser
from app.rag.kg.utils import get_logger

logger = get_logger("kg.extract.heuristic")

_ACRONYM_OR_STANDARD_RE = re.compile(
    r"\b(?:RFC\s?-?\d{3,5}|HTTP/[0-9.]+|[A-Z][A-Z0-9][A-Z0-9.+/_-]{1,})\b"
)
_TITLE_PHRASE_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9.+/_-]{2,}(?:\s+[A-Z][A-Za-z0-9.+/_-]{2,}){0,4}\b"
)
_CJK_TERM_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9]{2,18}(?:协议|模型|系统|知识库|数据集|检索|图谱|实体|切块|治理|解析|入库)"
)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s*")
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_LEADING_ENTITY_STOP_RE = re.compile(r"^(?:the|a|an)\s+", flags=re.IGNORECASE)

_STOP_PHRASES = {
    "abstract",
    "copyright notice",
    "table of contents",
    "contents",
    "overview",
    "introduction",
    "document structure",
    "terms and definitions",
    "notational conventions",
    "target",
    "context",
}


class HeuristicExtractor:
    """Dependency-free KG extractor for local/preflight graph construction.

    It is intentionally conservative: generate one event per target chunk and
    attach high-signal entities with exact evidence quotes. This keeps the graph
    useful for smoke tests, POC sizing and fallback operation when an external
    LLM provider is unavailable.
    """

    def __init__(self) -> None:
        self._parser = EntityValueParser()

    def _entity_type(self, name: str) -> str:
        value = str(name or "").strip()
        upper = value.upper()
        if re.fullmatch(r"RFC\s?-?\d{3,5}", value, flags=re.IGNORECASE):
            return "standard"
        if upper in {"IETF", "Mozilla", "Fastly", "OpenAI", "Alibaba", "DashScope"}:
            return "organization"
        if upper in {"QUIC", "HTTP", "HTTP/3", "TLS", "TCP", "UDP", "API", "RAG", "KG", "OCR"}:
            return "protocol"
        if value in {"FastAPI", "HTTPX", "Flask", "MimirQ", "Milvus", "PostgreSQL"}:
            return "software"
        return "concept"

    def _candidate_entities(self, text: str, *, max_entities: int) -> list[dict[str, Any]]:
        clean = str(text or "")
        if not clean.strip():
            return []

        candidates: OrderedDict[str, str] = OrderedDict()
        for regex in (_ACRONYM_OR_STANDARD_RE, _TITLE_PHRASE_RE, _CJK_TERM_RE):
            for match in regex.finditer(clean):
                raw = re.sub(r"\s+", " ", match.group(0)).strip(" \t\r\n.,;:()[]{}<>")
                raw = _LEADING_ENTITY_STOP_RE.sub("", raw).strip()
                if not raw:
                    continue
                normalized = self._parser.normalize_name(raw)
                if not normalized or normalized in _STOP_PHRASES:
                    continue
                if len(normalized) < 2:
                    continue
                if normalized.isdigit():
                    continue
                # Avoid turning long sentence fragments into graph nodes.
                if len(raw) > 80 or len(raw.split()) > 6:
                    continue
                candidates.setdefault(normalized, raw)
                if len(candidates) >= max_entities:
                    break
            if len(candidates) >= max_entities:
                break

        entities: list[dict[str, Any]] = []
        for normalized, surface in candidates.items():
            entities.append(
                {
                    "name": surface,
                    "normalized_name": normalized,
                    "type": self._parser.normalize_type(self._entity_type(surface)),
                    "description": "",
                    "evidence_quote": surface,
                    "score": 0.65,
                }
            )
        return entities

    def _event_title(self, text: str, *, chunk: DocumentChunk) -> str:
        clean = str(text or "").strip()
        heading = _HEADING_RE.search(clean)
        if heading:
            title = re.sub(r"\s+", " ", heading.group(1)).strip()
            if title:
                return title[:120]
        meta = getattr(chunk, "doc_metadata", None)
        meta_dict = meta if isinstance(meta, dict) else {}
        doc_title = str(meta_dict.get("document_title") or "").strip()
        if doc_title:
            return doc_title[:120]
        return f"Chunk {getattr(chunk, 'chunk_index', 0)} key concepts"

    def _event_summary(self, text: str, *, title: str) -> str:
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if not clean:
            return title
        sentences = re.split(r"(?<=[.!?。！？])\s+", clean)
        for sentence in sentences:
            value = sentence.strip()
            if len(value) >= 40:
                return value[:320]
        return clean[:320] or title

    def _fact_title(self, text: str, *, chunk: DocumentChunk) -> str:
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if clean:
            return clean[:120]
        return self._event_title(text, chunk=chunk)

    def _event_fact_candidates(
        self,
        text: str,
        *,
        max_events: int,
        max_entities_per_event: int,
    ) -> list[tuple[str, list[dict[str, Any]]]]:
        parts: list[str] = []
        for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _HEADING_RE.match(line) or _TABLE_SEPARATOR_RE.match(line):
                continue
            line = _BULLET_PREFIX_RE.sub("", line).strip()
            if not line:
                continue
            for raw_part in _SENTENCE_SPLIT_RE.split(line):
                part = re.sub(r"\s+", " ", raw_part).strip(" \t\r\n-|")
                if not part:
                    continue
                if len(part) < 16 and not _ACRONYM_OR_STANDARD_RE.search(part):
                    continue
                parts.append(part)

        if not parts:
            clean = re.sub(r"\s+", " ", str(text or "")).strip()
            if clean:
                parts.append(clean)

        rows: list[tuple[str, list[dict[str, Any]]]] = []
        seen: set[str] = set()
        for part in parts:
            key = part.casefold()
            if key in seen:
                continue
            seen.add(key)
            entities = self._candidate_entities(part, max_entities=max(1, int(max_entities_per_event or 30)))
            if not entities:
                continue
            rows.append((part, entities))
            if len(rows) >= max(1, int(max_events or 1)):
                break

        if not rows:
            entities = self._candidate_entities(text, max_entities=max(1, int(max_entities_per_event or 30)))
            if entities:
                rows.append((re.sub(r"\s+", " ", str(text or "")).strip(), entities))
        return rows

    async def extract_from_sections(
        self,
        sections: list[DocumentChunk],
        batch_index: int,
        *,
        max_events: int = 3,
        max_entities_per_event: int = 30,
    ) -> list[dict[str, Any]]:
        if not sections:
            return []
        target = sections[0]
        text = str(getattr(target, "content", "") or "").strip()
        if not text:
            return []

        max_events_i = max(1, int(max_events or 1))
        rows = self._event_fact_candidates(
            text,
            max_events=max_events_i,
            max_entities_per_event=max_entities_per_event,
        )
        if not rows:
            return []

        events: list[dict[str, Any]] = []
        entity_total = 0
        for fact, entities in rows[:max_events_i]:
            title = self._fact_title(fact, chunk=target)
            summary = self._event_summary(fact, title=title)
            entity_total += len(entities)
            events.append(
                {
                    "title": title,
                    "summary": summary,
                    "content": summary,
                    "entities": entities,
                    "chunk_id": str(getattr(target, "id", "") or ""),
                }
            )

        logger.info("Batch %s heuristic extracted %s events / %s entities", batch_index, len(events), entity_total)
        return events
