"""
Document Q&A generation/indexing.

This feature creates an optional "FAQ-like" retrieval channel by generating (or extracting)
question-answer pairs from an existing document, then persisting them as extra chunks.

Design notes:
- Best-effort: vector/BM25 updates are attempted but failures should not corrupt the DB.
- Safe-by-default: if LLM is not configured, fall back to regex extraction only.
- Tagging: generated chunks are marked with `file_type=qa` in chunk metadata so callers can
  include/exclude them via metadata_filter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk, DocumentParsedContent
from app.rag.core.logging import get_logger
from app.rag.retriever import hybrid_retriever
from app.services.indexer import Indexer
from app.storage.vector.factory import get_vector_store

logger = get_logger("services.document_qa")

_DOCUMENT_QA_DEGRADED_LOG_MSG = (
    "Document QA degraded: feature=%s dependency=%s reason=%s remediation=%s error=%s"
)


@dataclass(frozen=True)
class QAPair:
    question: str
    answer: str


@dataclass(frozen=True)
class DocumentQAGenerateResult:
    mode: str
    deleted: int
    created: int
    chunk_ids: list[UUID]
    preview: list[dict[str, str]]


_Q_PREFIXES: tuple[str, ...] = ("question", "q", "问题", "問題", "问")
_A_PREFIXES: tuple[str, ...] = ("answer", "a", "答")


def _split_prefixed_field(line: str, *, prefixes: tuple[str, ...], require_value: bool) -> str | None:
    """
    Best-effort parsing for Q/A lines like:
      Q: ...
      Question: ...
      问：...
      A: ...

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(line or "").lstrip()
    if not s:
        return None

    for prefix in prefixes:
        p = str(prefix or "")
        if not p:
            continue

        if p.isascii():
            if len(s) < len(p) or s[: len(p)].casefold() != p.casefold():
                continue
        else:
            if not s.startswith(p):
                continue

        rest = s[len(p) :].lstrip()
        if not rest or rest[0] not in (":", "："):
            continue
        value = rest[1:].lstrip()

        if require_value:
            value = value.strip()
            return value or None
        return value.strip()

    return None


def extract_qa_pairs_from_text(text: str, *, max_pairs: int) -> list[QAPair]:
    """
    Extract Q/A pairs from plain text using lightweight heuristics.

    Supported patterns (line-based):
      Q: ...
      A: ...
    """
    raw = (text or "").strip()
    if not raw or max_pairs <= 0:
        return []

    pairs: list[QAPair] = []
    question: str | None = None
    answer_lines: list[str] = []
    saw_answer_prefix = False

    for line in raw.splitlines():
        if len(pairs) >= max_pairs:
            break

        q_val = _split_prefixed_field(line, prefixes=_Q_PREFIXES, require_value=True)
        if q_val is not None:
            # Flush previous.
            if question and saw_answer_prefix:
                answer = "\n".join([a for a in answer_lines if a is not None]).strip()
                if answer:
                    pairs.append(QAPair(question=question.strip(), answer=answer))
            # Start new.
            question = q_val
            answer_lines = []
            saw_answer_prefix = False
            continue

        if question is None:
            continue

        a_val = _split_prefixed_field(line, prefixes=_A_PREFIXES, require_value=False)
        if a_val is not None:
            saw_answer_prefix = True
            rest = a_val.strip()
            if rest:
                answer_lines.append(rest)
            continue

        if saw_answer_prefix:
            # Continue answer until next Q: ... line.
            answer_lines.append(line.rstrip())

    if question and saw_answer_prefix and len(pairs) < max_pairs:
        answer = "\n".join([a for a in answer_lines if a is not None]).strip()
        if answer:
            pairs.append(QAPair(question=question.strip(), answer=answer))

    return pairs[:max_pairs]


def _llm_enabled() -> bool:
    return bool((settings.LLM_API_KEY or "").strip())


def _generate_pairs(source_text: str, *, num_pairs: int, prefer_llm: bool) -> tuple[str, list[QAPair]]:
    """
    Generate Q/A pairs via LLM (when enabled) or extract via regex as fallback.

    Returns (mode, pairs) where mode is one of: llm | extract | none
    """
    raw = (source_text or "").strip()
    n = max(0, int(num_pairs or 0))
    if not raw or n <= 0:
        return "none", []

    if bool(prefer_llm) and _llm_enabled():
        try:
            pairs = generate_qa_pairs_with_llm(raw, num_pairs=n)
            if pairs:
                return "llm", pairs
        except Exception as exc:  # noqa: BLE001
            # Best-effort: fall back to extraction, but make the degradation observable.
            logger.warning(
                _DOCUMENT_QA_DEGRADED_LOG_MSG,
                "qa_llm_generation",
                "llm",
                "llm_failed",
                "check LLM_API_KEY/LLM_API_BASE/LLM_MODEL and network access",
                str(exc)[:200],
            )

    pairs = extract_qa_pairs_from_text(raw, max_pairs=n)
    return ("extract", pairs) if pairs else ("none", [])


def generate_qa_pairs_with_llm(text: str, *, num_pairs: int) -> list[QAPair]:
    """
    Generate Q/A pairs using the configured LLM (OpenAI-compatible).

    Raises:
        RuntimeError: When LLM is not configured.
    """
    if not _llm_enabled():
        raise RuntimeError("LLM is not configured")

    from langchain_core.output_parsers import JsonOutputParser  # noqa: WPS433
    from langchain_core.prompts import PromptTemplate  # noqa: WPS433
    from langchain_openai import ChatOpenAI  # noqa: WPS433

    prompt_text = """You are an expert knowledge base curator.

Generate {num_pairs} high-quality FAQ-style question/answer pairs based ONLY on the given text.

Text:
{text}

Requirements:
- Questions should be answerable from the text.
- Answers must be short and grounded in the text.
- Avoid duplicates and overly generic questions.

Return JSON:
{{
  "pairs": [
    {{"question": "...", "answer": "..."}}
  ]
}}"""

    llm = ChatOpenAI(
        model=(settings.LLM_MODEL_FAST or settings.LLM_MODEL),
        api_key=settings.LLM_API_KEY,
        base_url=normalize_openai_compatible_base_url(settings.LLM_API_BASE),
        temperature=0.2,
        timeout=int(getattr(settings, "LLM_TIMEOUT", 60) or 60),
    )
    parser = JsonOutputParser()
    prompt = PromptTemplate(template=prompt_text, input_variables=["text", "num_pairs"])
    chain = prompt | llm | parser

    result = chain.invoke({"text": (text or "")[:12000], "num_pairs": int(num_pairs)})
    if not isinstance(result, dict):
        return []
    pairs_raw = result.get("pairs")
    if not isinstance(pairs_raw, list):
        return []

    pairs: list[QAPair] = []
    for item in pairs_raw:
        if len(pairs) >= num_pairs:
            break
        if not isinstance(item, dict):
            continue
        q = str(item.get("question") or "").strip()
        a = str(item.get("answer") or "").strip()
        if not q or not a:
            continue
        pairs.append(QAPair(question=q, answer=a))
    return pairs


def _active_pipeline_hash(doc_meta: dict[str, Any]) -> str:
    return str((doc_meta or {}).get("active_pipeline_hash") or (doc_meta or {}).get("pipeline_hash") or "").strip()


def _active_doc_pipeline_key(document_id: UUID, doc_meta: dict[str, Any]) -> str:
    h = _active_pipeline_hash(doc_meta)
    return f"{document_id}:{h}" if h else str(document_id)


def _get_source_text(db: Session, *, tenant_id: UUID, document_id: UUID, max_chars: int) -> str:
    """
    Best-effort source text for Q&A generation.

    Preference:
    - Persisted parsed markdown (cleaned)
    - Fallback: join active chunks
    """
    max_chars_eff = max(0, int(max_chars or 0))
    if max_chars_eff <= 0:
        max_chars_eff = 12_000

    row = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.tenant_id == tenant_id, DocumentParsedContent.document_id == document_id)
        .first()
    )
    if row and (row.markdown_content or "").strip():
        return str(row.markdown_content or "")[:max_chars_eff]

    # Fallback: assemble from chunks (best-effort).
    chunks = (
        db.query(DocumentChunk.content)
        .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(2000)
        .all()
    )
    buf: list[str] = []
    total = 0
    for (content,) in chunks:
        s = (content or "").strip()
        if not s:
            continue
        remaining = max_chars_eff - total
        if remaining <= 0:
            break
        take = s[:remaining]
        buf.append(take)
        total += len(take)
        if total >= max_chars_eff:
            break
    return "\n\n".join(buf)


def generate_and_index_document_qa(
    db: Session,
    *,
    tenant_id: UUID,
    document: DBDocument,
    num_pairs: int = 20,
    replace_existing: bool = True,
    prefer_llm: bool = True,
    max_source_chars: int = 12_000,
    preview_pairs: int = 5,
) -> DocumentQAGenerateResult:
    """
    Generate/extract Q&A pairs and store them as additional chunks under the active pipeline version.
    """
    document_id = UUID(str(document.id))
    doc_meta = dict(getattr(document, "doc_metadata", None) or {})
    active_hash = _active_pipeline_hash(doc_meta)
    active_key = _active_doc_pipeline_key(document_id, doc_meta)

    # 1) Delete existing QA chunks (best-effort).
    deleted = 0
    if replace_existing:
        rows = (
            db.query(DocumentChunk.id, DocumentChunk.doc_metadata)
            .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
            .all()
        )
        qa_ids: list[UUID] = []
        for cid, meta in rows:
            m = meta if isinstance(meta, dict) else {}
            if str(m.get("doc_pipeline_key") or "").strip() != active_key:
                continue
            if str(m.get("file_type") or "").strip().lower() != "qa":
                continue
            qa_ids.append(UUID(str(cid)))

        if qa_ids:
            vector_store = get_vector_store()

            vector_delete_errors = 0
            vector_delete_first_error: str | None = None
            bm25_delete_errors = 0
            bm25_delete_first_error: str | None = None

            for cid in qa_ids:
                try:
                    vector_store.delete_by_document_id_and_filter(
                        document_id=document_id,
                        tenant_id=tenant_id,
                        metadata_filter={"chunk_id": {"$eq": str(cid)}},
                    )
                except NotImplementedError:
                    # If vector backend can't selectively delete, leave vectors as-is.
                    pass
                except Exception as exc:  # noqa: BLE001
                    vector_delete_errors += 1
                    if vector_delete_first_error is None:
                        vector_delete_first_error = str(exc)[:200]

                try:
                    hybrid_retriever.remove_from_bm25_index_by_metadata_filter(
                        tenant_id=tenant_id,
                        metadata_filter={"chunk_id": {"$eq": str(cid)}},
                    )
                except Exception as exc:  # noqa: BLE001
                    bm25_delete_errors += 1
                    if bm25_delete_first_error is None:
                        bm25_delete_first_error = str(exc)[:200]

            if vector_delete_errors:
                logger.warning(
                    "Document QA degraded: feature=%s dependency=%s reason=%s remediation=%s errors=%s first_error=%s",
                    "qa_vector_delete",
                    str(getattr(settings, "VECTOR_BACKEND", "") or "vector_store"),
                    "delete_failed",
                    "check vector backend health/permissions; stale vectors may remain",
                    int(vector_delete_errors),
                    vector_delete_first_error or "",
                )
            if bm25_delete_errors:
                logger.warning(
                    "Document QA degraded: feature=%s dependency=%s reason=%s remediation=%s errors=%s first_error=%s",
                    "qa_bm25_delete",
                    "bm25",
                    "delete_failed",
                    "check BM25 index backend; stale keywords may remain",
                    int(bm25_delete_errors),
                    bm25_delete_first_error or "",
                )

            db.query(DocumentChunk).filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
                DocumentChunk.id.in_(qa_ids),
            ).delete(synchronize_session=False)
            db.commit()
            deleted = len(qa_ids)

    # 2) Build source text.
    source_text = _get_source_text(db, tenant_id=tenant_id, document_id=document_id, max_chars=max_source_chars)
    if not source_text.strip():
        return DocumentQAGenerateResult(mode="none", deleted=deleted, created=0, chunk_ids=[], preview=[])

    # 3) Generate Q/A pairs.
    mode, pairs = _generate_pairs(source_text, num_pairs=int(num_pairs), prefer_llm=bool(prefer_llm))

    if not pairs:
        return DocumentQAGenerateResult(mode=mode, deleted=deleted, created=0, chunk_ids=[], preview=[])

    # 4) Determine next chunk_index in active pipeline version.
    q = db.query(func.max(DocumentChunk.chunk_index)).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
    )
    if active_key:
        q = q.filter(DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key)  # type: ignore[attr-defined]
    max_idx = q.scalar()
    next_index = int(max_idx or -1) + 1

    # 5) Prepare chunk payloads.
    source_label = str(getattr(document, "filename", "") or "document").strip()[:500] or "document"
    records: list[dict[str, Any]] = []
    chunk_ids: list[UUID] = []
    chunk_metas: list[dict[str, Any]] = []

    for pair in pairs:
        cid = uuid.uuid4()
        content = f"Q: {pair.question.strip()}\nA: {pair.answer.strip()}".strip()

        meta: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "document_id": str(document_id),
            "chunk_id": str(cid),
            "chunk_index": int(next_index),
            "file_type": "qa",
            "source": source_label,
            "chunk_role": "qa",
            "qa_question": pair.question.strip(),
            "qa_answer": pair.answer.strip(),
            "qa_mode": mode,
            "qa_generated": True,
        }
        if active_hash:
            meta["pipeline_hash"] = active_hash[:64]
            meta["doc_pipeline_key"] = active_key

        records.append({"content": content, "metadata": meta})
        chunk_ids.append(cid)
        chunk_metas.append(meta)
        next_index += 1

    # 6) Vector indexing (best-effort).
    vector_ids: list[str | None] = [None] * len(records)
    try:
        ids = list(get_vector_store().add_documents(records, document_id, tenant_id))
        for i, vid in enumerate(ids):
            if i >= len(vector_ids):
                break
            if vid:
                vector_ids[i] = str(vid)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            _DOCUMENT_QA_DEGRADED_LOG_MSG,
            "qa_vector_index",
            str(getattr(settings, "VECTOR_BACKEND", "") or "vector_store"),
            "index_failed",
            "check vector backend health/config; chunks saved but may not be retrievable via vectors",
            str(exc)[:200],
        )
        vector_ids = [None] * len(records)

    # 7) Persist chunks.
    db_chunks: list[DocumentChunk] = []
    for i, cid in enumerate(chunk_ids):
        chunk = DocumentChunk(
            id=cid,
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_index=int(chunk_metas[i].get("chunk_index") or i),
            content=str(records[i].get("content") or ""),
            page_number=None,
            start_char=None,
            end_char=None,
            doc_metadata=chunk_metas[i],
            vector_id=vector_ids[i],
        )
        db_chunks.append(chunk)
        db.add(chunk)

    db.commit()

    # 8) BM25 upsert (best-effort).
    try:
        Indexer(db)._update_bm25_for_chunks(
            db_chunks=db_chunks,
            tenant_id=tenant_id,
            document_id=document_id,
            default_source=source_label,
            enable_bm25=bool(getattr(settings, "BM25_INDEX_ENABLED", True)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            _DOCUMENT_QA_DEGRADED_LOG_MSG,
            "qa_bm25_upsert",
            "bm25",
            "index_failed",
            "check BM25 index backend; chunks saved but keyword search may miss them",
            str(exc)[:200],
        )

    # 9) Update document stats (best-effort).
    try:
        stat_q = db.query(func.count(DocumentChunk.id), func.sum(func.length(DocumentChunk.content))).filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
        )
        if active_key:
            stat_q = stat_q.filter(DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key)  # type: ignore[attr-defined]
        cnt, total_chars = stat_q.first() or (None, None)
        document.chunk_count = int(cnt or 0)
        document.total_characters = int(total_chars or 0)
        db.commit()
    except Exception:
        db.rollback()

    preview: list[dict[str, str]] = []
    for pair in pairs[: max(0, min(int(preview_pairs or 0), 20))]:
        preview.append({"question": pair.question.strip(), "answer": pair.answer.strip()})

    return DocumentQAGenerateResult(
        mode=mode,
        deleted=int(deleted),
        created=len(chunk_ids),
        chunk_ids=list(chunk_ids),
        preview=preview,
    )


__all__ = [
    "DocumentQAGenerateResult",
    "QAPair",
    "extract_qa_pairs_from_text",
    "generate_and_index_document_qa",
]
