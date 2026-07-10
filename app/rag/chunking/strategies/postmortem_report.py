"""
Incident postmortem / RCA report aware chunking strategy.

Targets incident reports with common sections such as:
- Summary / Impact / Timeline / Root Cause / Detection / Resolution / Action Items / Lessons
- 摘要/总结 / 影响 / 时间线 / 根因 / 检测 / 解决 / 行动项 / 经验教训

Splits the document into these sections first, then applies a fallback splitter
while preserving character offsets.
"""


from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import (
    normalize_spaces_lower,
    parse_markdown_hash_heading,
    strip_numbered_heading_prefix,
)


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    plain: str


@dataclass(frozen=True)
class _Heading:
    start: int
    end: int
    title: str
    key: str
    level: int


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: _Heading | None


_SECTION_SYNONYMS: dict[str, list[str]] = {
    "summary": ["summary", "overview", "incident summary", "postmortem", "rca", "摘要", "总结", "概述", "事件概述", "复盘"],
    "impact": ["impact", "customer impact", "影响", "影响范围", "用户影响"],
    "timeline": ["timeline", "chronology", "时间线", "时间轴", "事件时间线", "事件记录"],
    "root_cause": ["root cause", "root causes", "cause", "根因", "原因分析", "根本原因"],
    "detection": ["detection", "发现", "检测", "告警", "监控"],
    "resolution": ["resolution", "mitigation", "fix", "解决", "修复", "处置", "恢复", "应对"],
    "action_items": ["action items", "follow-ups", "tasks", "行动项", "后续行动", "整改", "改进项"],
    "lessons": ["lessons learned", "what went well", "what went wrong", "经验教训", "复盘结论", "反思"],
}

_TITLE_TO_KEY: dict[str, str] = {}
for k, vals in _SECTION_SYNONYMS.items():
    for v in vals:
        _TITLE_TO_KEY[normalize_spaces_lower(v)] = k


def _iter_lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, plain=raw.rstrip("\r\n")))
    if not out and text:
        out.append(_Line(start=0, end=len(text), plain=text))
    return out


def _parse_heading_line(plain: str) -> tuple[str, str, int] | None:
    s = (plain or "").strip()
    if not s:
        return None

    parsed = parse_markdown_hash_heading(s)
    if parsed is not None:
        level, title = parsed
        title = str(title).rstrip(":：").strip()
        key = _TITLE_TO_KEY.get(normalize_spaces_lower(title))
        if key:
            return title, key, int(level)
        return None

    s2 = strip_numbered_heading_prefix(s).strip()
    s2 = s2.rstrip(":：").strip()
    if not s2 or len(s2) > 80:
        return None
    key = _TITLE_TO_KEY.get(normalize_spaces_lower(s2))
    if key:
        return s2, key, 2
    return None


def _iter_headings(text: str) -> list[_Heading]:
    headings: list[_Heading] = []
    for ln in _iter_lines(text):
        parsed = _parse_heading_line(ln.plain)
        if not parsed:
            continue
        title, key, level = parsed
        headings.append(_Heading(start=ln.start, end=ln.end, title=title, key=key, level=level))

    deduped: list[_Heading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[_Heading]) -> list[_Section]:
    if not headings:
        return [_Section(start=0, end=len(text), heading=None)]
    sections: list[_Section] = []
    first = headings[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, heading=None))
    for idx, h in enumerate(headings):
        start = h.start
        end = headings[idx + 1].start if idx + 1 < len(headings) else len(text)
        sections.append(_Section(start=start, end=end, heading=h))
    return sections


def looks_like_postmortem_report(text: str) -> bool:
    if not text or len(text) < 160:
        return False
    headings = _iter_headings(text)
    keys = {h.key for h in headings}
    if len(keys) >= 5:
        return True
    lowered = (text or "").lower()
    if len(keys) >= 3 and any(k in lowered for k in ("postmortem", "root cause", "rca", "incident", "根因", "复盘")):
        return True
    return False


class PostmortemReportChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", "。", "！", "？", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            headings = _iter_headings(text)
            sections = _build_sections(text, headings)

            current: _Heading | None = None
            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                if section.heading is not None:
                    current = section.heading

                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "postmortem_report"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "postmortem")
                    if current is not None:
                        meta["postmortem_section"] = current.key
                        meta["postmortem_section_title"] = current.title

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
