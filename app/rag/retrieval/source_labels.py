"""Source label helpers for generation and citation metadata."""

import re
from pathlib import Path
from app.rag.core.metadata import _stringified_metadata_text
from typing import Any

_DEEPDOC_BOX_RE = re.compile(r"@@[^#\n]{1,160}##")
_UUID_PDF_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf$",
    flags=re.IGNORECASE,
)
_ARXIV_SUFFIX_RE = re.compile(r"([_-])(?:v?\d{4}\.\d{4,6}|[a-f0-9]{32,})(?:v\d+)?$", flags=re.IGNORECASE)
_SECTION_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\s+)?(?:abstract|keywords?|introduction|references)\b", re.IGNORECASE
)
_AUTHOR_AFFILIATION_RE = re.compile(
    r"(@|\{|\}|university|institute|department|google ai|facebook ai|princeton|microsoft|research|school of)",
    flags=re.IGNORECASE,
)
_SOURCE_IDENTIFICATION_RE = re.compile(
    r"\b(?:which|what)\s+(?:paper|survey|document|source|file)\b",
    flags=re.IGNORECASE,
)


def _clean_line(raw: str) -> str:
    text = re.sub(r"\s+", " ", raw.strip())
    text = text.strip(" #\t\r\n")
    return text


def _is_title_like(line: str, *, first: bool) -> bool:
    text = _clean_line(line)
    if not text:
        return False
    if len(text) < 4 or len(text) > 140:
        return False
    if _SECTION_HEADING_RE.search(text):
        return False
    if _AUTHOR_AFFILIATION_RE.search(text):
        return False
    if text.count(",") >= 2:
        return False
    if re.fullmatch(r"\d+", text):
        return False
    # A first line such as "1 Introduction" is a section heading, not a paper title.
    if first and re.match(r"^\d+(?:\.\d+)*\s+[A-Z][A-Za-z -]{2,}$", text):
        return False
    return bool(re.search(r"[A-Za-z]{3,}", text))


def _title_from_first_chunk(first_chunk_content: Any) -> str | None:
    if first_chunk_content is None:
        return None
    raw = str(first_chunk_content).strip()
    if not raw:
        return None

    normalized = _DEEPDOC_BOX_RE.sub("\n", raw)
    normalized = normalized.replace("##", "\n")
    lines = [_clean_line(line) for line in normalized.splitlines()]
    lines = [line for line in lines if line]

    title_lines: list[str] = []
    for line in lines[:12]:
        if not _is_title_like(line, first=not title_lines):
            if title_lines:
                break
            continue
        title_lines.append(line)
        if len(title_lines) >= 3:
            break

    if not title_lines:
        return None
    title = _clean_line(" ".join(title_lines))[:200]
    return title


def _title_from_filename(filename: Any) -> str | None:
    if filename is None:
        return None
    raw = str(filename).strip()
    if not raw:
        return None
    try:
        stem = Path(raw).name
        stem = Path(stem).stem
    except Exception:
        stem = raw.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    stem = _ARXIV_SUFFIX_RE.sub("", stem)
    stem = re.sub(r"[-_]+", " ", stem)
    stem = _clean_line(stem)[:200]
    return stem if stem else None


def derive_document_title(
    *,
    filename: Any,
    doc_metadata: dict[str, Any] | None,
    first_chunk_content: Any = None,
) -> str | None:
    """Derive a human-readable document title for answer generation."""

    meta = doc_metadata if isinstance(doc_metadata, dict) else {}
    for key in ("document_title", "doc_title", "title", "name"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_line(value)[:200]

    title = _title_from_first_chunk(first_chunk_content)
    if title:
        return title

    return _title_from_filename(filename)


def should_replace_source_label(source: Any, *, document_id: Any) -> bool:
    """Return true when `source` is a low-value generated label such as UUID.pdf."""

    if source is None:
        return True
    text = str(source).strip()
    if not text:
        return True
    if text.lower() in {"unknown", "document", "source"}:
        return True
    name = text.rsplit("/", 1)[-1]
    if _UUID_PDF_RE.fullmatch(name):
        return True
    doc_id = str(document_id).strip().lower() if document_id is not None else None
    return bool(doc_id and name.lower() in {doc_id, f"{doc_id}.pdf"})


def _source_answer_title_and_filename(doc: Any) -> tuple[str | None, str | None]:
    meta = getattr(doc, "metadata", None) or {}
    if not isinstance(meta, dict):
        return None, None

    title = _stringified_metadata_text(meta, "document_title") or _stringified_metadata_text(meta, "doc_title") or _stringified_metadata_text(meta, "title")
    if not title:
        title = None
    filename = _stringified_metadata_text(meta, "filename") or _stringified_metadata_text(meta, "source")
    if not filename:
        filename = None
    return title, filename


def _source_answer_label(question: str) -> str:
    q = question.lower()
    if "survey" in q:
        return "survey"
    if "document" in q:
        return "document"
    if "source" in q:
        return "source"
    if "file" in q:
        return "file"
    return "paper"


def maybe_build_source_identification_answer(*, question: str, docs: list[Any] | None) -> str | None:
    """
    Build a deterministic answer for source-identification questions.

    This prevents the generator from ignoring a precise retrieved source title and
    answering with a filename or an unnecessary abstention.
    """

    if not _SOURCE_IDENTIFICATION_RE.search(question):
        return None
    if not docs:
        return None

    doc = docs[0]
    title, filename = _source_answer_title_and_filename(doc)
    if not title:
        title = filename
    if not title:
        return None

    label = _source_answer_label(question)

    suffix = ""
    if filename and filename != title:
        suffix = f" (source file: {filename})"
    return f'The {label} is "{title}"{suffix}.'
