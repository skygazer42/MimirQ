
import asyncio
import re
from collections import OrderedDict
from typing import Any

from app.models.document import DocumentChunk
from app.rag.kg.extraction.parser import EntityValueParser
from app.rag.kg.utils import get_logger

logger = get_logger("kg.extract.heuristic")

_ACRONYM_OR_STANDARD_RE = re.compile(
    r"\b(?:RFC\s?-?\d{3,5}|HTTP/[0-9.]+|[A-Z][A-Z0-9][A-Z0-9.+/_-]+)\b"
)
_TITLE_PHRASE_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9.+/_-]{2,}(?:\s+[A-Z][A-Za-z0-9.+/_-]{2,}){0,4}\b"
)
_CJK_TERM_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9]{2,18}(?:协议|模型|系统|知识库|数据集|检索|图谱|实体|切块|治理|解析|入库)"
)
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


def _collapse_spaces(value: str) -> str:
    return " ".join(str(value or "").split())


def _line_heading(line: str) -> str | None:
    raw = str(line or "").rstrip()
    leading_spaces = len(raw) - len(raw.lstrip(" "))
    if leading_spaces > 3:
        return None
    stripped = raw.lstrip(" ")
    hashes = 0
    while hashes < len(stripped) and stripped[hashes] == "#" and hashes < 6:
        hashes += 1
    if hashes <= 0 or hashes >= len(stripped) or not stripped[hashes].isspace():
        return None
    title = _collapse_spaces(stripped[hashes:])
    return title or None


def _extract_heading(text: str) -> str | None:
    for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        title = _line_heading(line)
        if title:
            return title
    return None


def _trim_table_edge_pipes(text: str) -> str:
    trimmed = str(text or "").strip()
    if trimmed.startswith("|"):
        trimmed = trimmed[1:]
    if trimmed.endswith("|"):
        trimmed = trimmed[:-1]
    return trimmed


def _is_table_separator_cell(cell: str) -> bool:
    core = str(cell or "").strip()
    if not core:
        return False
    if core.startswith(":"):
        core = core[1:]
    if core.endswith(":"):
        core = core[:-1]
    return len(core) >= 3 and all(ch == "-" for ch in core)


def _is_table_separator(line: str) -> bool:
    text = str(line or "").strip()
    if not text or "-" not in text:
        return False
    cells = [cell.strip() for cell in _trim_table_edge_pipes(text).split("|")]
    return len(cells) >= 2 and all(_is_table_separator_cell(cell) for cell in cells)


def _strip_bullet_prefix(line: str) -> str:
    text = str(line or "").lstrip()
    if len(text) >= 2 and text[0] in {"-", "*", "+"} and text[1].isspace():
        return text[2:].lstrip()
    cursor = 0
    while cursor < len(text) and text[cursor].isdigit():
        cursor += 1
    if cursor > 0 and cursor + 1 < len(text) and text[cursor] in {".", ")"} and text[cursor + 1].isspace():
        return text[cursor + 2 :].lstrip()
    return text


def _split_sentences(line: str) -> list[str]:
    text = str(line or "")
    parts: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if char not in ".!?。！？":
            continue
        end = index + 1
        parts.append(text[start:end])
        start = end
        while start < len(text) and text[start].isspace():
            start += 1
    if start < len(text):
        parts.append(text[start:])
    return parts or [text]


def _normalized_entity_candidate(parser: EntityValueParser, value: str) -> tuple[str, str] | None:
    raw = _collapse_spaces(value).strip(" \t\r\n.,;:()[]{}<>")
    raw = _LEADING_ENTITY_STOP_RE.sub("", raw).strip()
    if not raw:
        return None
    normalized = parser.normalize_name(raw)
    if not normalized or normalized in _STOP_PHRASES:
        return None
    if len(normalized) < 2 or normalized.isdigit():
        return None
    # Avoid turning long sentence fragments into graph nodes.
    if len(raw) > 80 or len(raw.split()) > 6:
        return None
    return normalized, raw


def _iter_line_fact_parts(raw_line: str) -> list[str]:
    line = str(raw_line or "").strip()
    if not line or _line_heading(line) or _is_table_separator(line):
        return []
    line = _strip_bullet_prefix(line).strip()
    if not line:
        return []

    parts: list[str] = []
    for raw_part in _split_sentences(line):
        part = _collapse_spaces(raw_part).strip(" \t\r\n-|")
        if not part:
            continue
        if len(part) < 16 and not _ACRONYM_OR_STANDARD_RE.search(part):
            continue
        parts.append(part)
    return parts


def _iter_fact_parts(text: str) -> list[str]:
    parts: list[str] = []
    for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        parts.extend(_iter_line_fact_parts(raw_line))
    return parts


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
                candidate = _normalized_entity_candidate(self._parser, match.group(0))
                if candidate is None:
                    continue
                normalized, raw = candidate
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
        heading = _extract_heading(clean)
        if heading:
            return heading[:120]
        meta = getattr(chunk, "doc_metadata", None)
        meta_dict = meta if isinstance(meta, dict) else {}
        doc_title = str(meta_dict.get("document_title") or "").strip()
        if doc_title:
            return doc_title[:120]
        return f"Chunk {getattr(chunk, 'chunk_index', 0)} key concepts"

    def _event_summary(self, text: str, *, title: str) -> str:
        clean = _collapse_spaces(str(text or ""))
        if not clean:
            return title
        sentences = _split_sentences(clean)
        for sentence in sentences:
            value = sentence.strip()
            if len(value) >= 40:
                return value[:320]
        return clean[:320] or title

    def _fact_title(self, text: str, *, chunk: DocumentChunk) -> str:
        clean = _collapse_spaces(str(text or ""))
        if clean:
            return clean[:120]
        return self._event_title(text, chunk=chunk)

    def _fact_rows_from_parts(
        self,
        parts: list[str],
        *,
        max_events: int,
        max_entities_per_event: int,
    ) -> list[tuple[str, list[dict[str, Any]]]]:
        rows: list[tuple[str, list[dict[str, Any]]]] = []
        seen: set[str] = set()
        entity_limit = max(1, int(max_entities_per_event or 30))
        row_limit = max(1, int(max_events or 1))
        for part in parts:
            key = part.casefold()
            if key in seen:
                continue
            seen.add(key)
            entities = self._candidate_entities(part, max_entities=entity_limit)
            if not entities:
                continue
            rows.append((part, entities))
            if len(rows) >= row_limit:
                break
        return rows

    def _event_fact_candidates(
        self,
        text: str,
        *,
        max_events: int,
        max_entities_per_event: int,
    ) -> list[tuple[str, list[dict[str, Any]]]]:
        parts = _iter_fact_parts(text)

        if not parts:
            clean = _collapse_spaces(str(text or ""))
            if clean:
                parts.append(clean)

        rows = self._fact_rows_from_parts(
            parts,
            max_events=max_events,
            max_entities_per_event=max_entities_per_event,
        )
        if not rows:
            entities = self._candidate_entities(text, max_entities=max(1, int(max_entities_per_event or 30)))
            if entities:
                rows.append((_collapse_spaces(str(text or "")), entities))
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

        # The extractor is CPU-bound but implements the async KG backend contract.
        await asyncio.sleep(0)
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
