"""
Resume / CV structured chunking strategy.

Targets resume-like documents with common section headings, e.g.:
- Education / Work Experience / Projects / Skills
- 教育经历 / 工作经历 / 项目经历 / 技能

The chunker splits the document into sections first, then applies a fallback
RecursiveCharacterTextSplitter inside each section to respect chunk_size and
chunk_overlap while preserving character offsets.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import parse_markdown_hash_heading


@dataclass(frozen=True)
class ResumeHeading:
    start: int
    end: int
    text: str
    key: str


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: ResumeHeading | None


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CN_MOBILE_RE = re.compile(r"\b1[3-9]\d{9}\b")

_EN_SECTIONS: dict[str, str] = {
    "summary": "summary",
    "profile": "summary",
    "objective": "summary",
    "contact": "contact",
    "education": "education",
    "work experience": "experience",
    "professional experience": "experience",
    "experience": "experience",
    "projects": "projects",
    "project": "projects",
    "skills": "skills",
    "skill": "skills",
    "certifications": "certifications",
    "certification": "certifications",
    "awards": "awards",
    "publications": "publications",
    "languages": "languages",
    "interests": "interests",
    "volunteer": "volunteer",
    "volunteering": "volunteer",
}

_CN_SECTIONS: dict[str, str] = {
    "个人信息": "contact",
    "联系方式": "contact",
    "教育经历": "education",
    "学历": "education",
    "工作经历": "experience",
    "实习经历": "experience",
    "项目经历": "projects",
    "技能": "skills",
    "技能特长": "skills",
    "自我评价": "summary",
    "个人总结": "summary",
    "证书": "certifications",
    "资格证书": "certifications",
    "获奖": "awards",
    "荣誉": "awards",
    "语言能力": "languages",
    "论文": "publications",
    "出版": "publications",
    "兴趣爱好": "interests",
    "志愿者": "volunteer",
    "培训经历": "training",
}

_EN_CANON = {re.sub(r"\s+", " ", k.strip().lower()): v for k, v in _EN_SECTIONS.items()}


def _normalize_title(raw: str) -> str:
    t = (raw or "").strip()
    if not t:
        return ""
    # Strip markdown heading marker if present.
    parsed = parse_markdown_hash_heading(t)
    if parsed is not None:
        _level, title = parsed
        t = title
    # Strip numbering prefixes like "1." / "1)" / "一、"
    t = re.sub(r"^\s*(?:\d{1,3}[.、)）]\s*|[一二三四五六七八九十]{1,3}[、.]\s*)", "", t).strip()
    t = t.strip(":：").strip()
    return t


def _section_key(title: str) -> str | None:
    if not title:
        return None
    if title in _CN_SECTIONS:
        return _CN_SECTIONS[title]
    lower = re.sub(r"\s+", " ", title.strip().lower())
    return _EN_CANON.get(lower)


def _iter_headings(text: str) -> list[ResumeHeading]:
    headings: list[ResumeHeading] = []
    if not text:
        return headings

    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)

        line = raw_line.strip()
        if not line:
            continue
        if len(line) > 120:
            continue

        title = _normalize_title(line)
        key = _section_key(title)
        if not key:
            continue

        headings.append(
            ResumeHeading(
                start=line_start,
                end=line_start + len(raw_line),
                text=title,
                key=key,
            )
        )

    deduped: list[ResumeHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[ResumeHeading]) -> list[_Section]:
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


def looks_like_resume(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    headings = _iter_headings(text)
    if len(headings) < 2:
        return False
    if _EMAIL_RE.search(text) or _CN_MOBILE_RE.search(text):
        return True
    lowered = text.lower()
    return ("linkedin" in lowered) or ("github" in lowered)


class ResumeStructuredChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "；", "，", ". ", "!", "?", " ", ""],
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

            current_section: ResumeHeading | None = None

            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                if section.heading is not None:
                    current_section = section.heading

                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "resume_structured"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    if current_section is not None:
                        meta["resume_section"] = current_section.key
                        meta["resume_section_title"] = current_section.text

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
