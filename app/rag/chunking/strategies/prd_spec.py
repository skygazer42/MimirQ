"""
PRD / requirements spec aware chunking strategy.

Targets product requirement documents with common sections such as:
- Background / Goals / Scope / Requirements / Non-functional / Acceptance / Risks
- 背景 / 目标 / 范围 / 需求 / 非功能 / 验收 / 风险 / 里程碑

The chunker splits the document into these sections first, then applies a
fallback RecursiveCharacterTextSplitter inside each section while preserving
character offsets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


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
    heading: Optional[_Heading]


_MD_HEADING_RE = re.compile(r"^\s*(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
_NUMBERED_PREFIX_RE = re.compile(r"^\s*(?:\d+(?:\.\d+){0,3}[\).\s]+)\s*")
_COLON_SUFFIX_RE = re.compile(r"\s*[:：]\s*$")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


_SECTION_SYNONYMS: Dict[str, List[str]] = {
    "background": ["background", "context", "背景", "背景介绍", "现状", "动机"],
    "goals": ["goals", "goal", "objectives", "目标", "目标与收益", "目的"],
    "scope": ["scope", "in scope", "out of scope", "范围", "范围界定", "不在范围"],
    "users": ["users", "user persona", "persona", "用户", "用户画像", "角色"],
    "requirements": ["requirements", "requirement", "需求", "功能需求", "需求列表", "需求说明"],
    "nonfunctional": ["non-functional", "nonfunctional", "nfr", "非功能", "性能", "安全", "可靠性"],
    "user_stories": ["user stories", "stories", "user story", "用户故事", "用例", "场景"],
    "acceptance": ["acceptance criteria", "acceptance", "验收标准", "验收", "验收条件"],
    "risks": ["risks", "risk", "风险", "风险评估", "风险与对策"],
    "milestones": ["milestones", "milestone", "timeline", "roadmap", "里程碑", "计划", "排期"],
    "constraints": ["constraints", "assumptions", "依赖", "约束", "假设", "限制条件"],
    "metrics": ["metrics", "success metrics", "kpi", "指标", "成功指标", "衡量标准"],
}

_TITLE_TO_KEY: Dict[str, str] = {}
for k, vals in _SECTION_SYNONYMS.items():
    for v in vals:
        _TITLE_TO_KEY[_norm(v)] = k


def _iter_lines(text: str) -> List[_Line]:
    out: List[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, plain=raw.rstrip("\r\n")))
    if not out and text:
        out.append(_Line(start=0, end=len(text), plain=text))
    return out


def _parse_heading_line(plain: str) -> Optional[Tuple[str, str, int]]:
    s = (plain or "").strip()
    if not s:
        return None

    m = _MD_HEADING_RE.match(s)
    if m:
        title = (m.group("title") or "").strip()
        title = _COLON_SUFFIX_RE.sub("", title).strip()
        level = len(m.group("marks") or "#")
        key = _TITLE_TO_KEY.get(_norm(title))
        if key:
            return title, key, int(level)
        return None

    # Numbered heading or plain heading.
    s2 = _NUMBERED_PREFIX_RE.sub("", s).strip()
    s2 = _COLON_SUFFIX_RE.sub("", s2).strip()
    if not s2 or len(s2) > 80:
        return None

    key = _TITLE_TO_KEY.get(_norm(s2))
    if key:
        return s2, key, 2
    return None


def _iter_headings(text: str) -> List[_Heading]:
    headings: List[_Heading] = []
    for ln in _iter_lines(text):
        parsed = _parse_heading_line(ln.plain)
        if not parsed:
            continue
        title, key, level = parsed
        headings.append(_Heading(start=ln.start, end=ln.end, title=title, key=key, level=level))

    deduped: List[_Heading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: List[_Heading]) -> List[_Section]:
    if not headings:
        return [_Section(start=0, end=len(text), heading=None)]
    sections: List[_Section] = []
    first = headings[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, heading=None))
    for idx, h in enumerate(headings):
        start = h.start
        end = headings[idx + 1].start if idx + 1 < len(headings) else len(text)
        sections.append(_Section(start=start, end=end, heading=h))
    return sections


def looks_like_prd_spec(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    headings = _iter_headings(text)
    keys = {h.key for h in headings}
    if len(keys) >= 5:
        return True
    lowered = (text or "").lower()
    # A weaker signal: at least 3 sections plus PRD-ish keywords.
    if len(keys) >= 3 and any(k in lowered for k in ("acceptance", "non-functional", "milestone", "roadmap", "user story", "验收", "里程碑", "非功能")):
        return True
    return False


class PRDSpecChunker(BaseChunker):
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

    def split_documents(self, documents: List[Document]) -> List[Document]:
        out: List[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            headings = _iter_headings(text)
            sections = _build_sections(text, headings)

            current: Optional[_Heading] = None
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
                    meta["chunk_strategy"] = "prd_spec"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "prd")
                    if current is not None:
                        meta["prd_section"] = current.key
                        meta["prd_section_title"] = current.title

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
