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

_DOCUMENT_QA_DEGRADED_LOG_MSG = "Document QA degraded: feature=%s dependency=%s reason=%s remediation=%s error=%s"


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


@dataclass
class _QAPairParseState:
    pairs: list[QAPair]
    question: str | None = None
    answer_lines: list[str] | None = None
    saw_answer_prefix: bool = False


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

    state = _QAPairParseState(pairs=[], answer_lines=[])

    for line in raw.splitlines():
        if len(state.pairs) >= max_pairs:
            break

        q_val = _split_prefixed_field(line, prefixes=_Q_PREFIXES, require_value=True)
        if q_val is not None:
            _flush_current_pair(state)
            state.question = q_val
            state.answer_lines = []
            state.saw_answer_prefix = False
            continue

        if state.question is None:
            continue

        a_val = _split_prefixed_field(line, prefixes=_A_PREFIXES, require_value=False)
        if a_val is not None:
            state.saw_answer_prefix = True
            rest = a_val.strip()
            if rest:
                state.answer_lines.append(rest)
            continue

        _append_answer_continuation(state, line)

    if len(state.pairs) < max_pairs:
        _flush_current_pair(state)

    return state.pairs[:max_pairs]


def _append_answer_continuation(state: _QAPairParseState, line: str) -> None:
    if state.saw_answer_prefix and state.answer_lines is not None:
        state.answer_lines.append(line.rstrip())


def _flush_current_pair(state: _QAPairParseState) -> None:
    if not state.question or not state.saw_answer_prefix or state.answer_lines is None:
        return
    answer = "\n".join(state.answer_lines).strip()
    if answer:
        state.pairs.append(QAPair(question=state.question.strip(), answer=answer))


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

    deleted = 0
    if replace_existing:
        qa_ids = _collect_active_qa_chunk_ids(db, tenant_id=tenant_id, document_id=document_id, active_key=active_key)
        deleted = _delete_existing_qa_chunks(
            db,
            tenant_id=tenant_id,
            document_id=document_id,
            qa_ids=qa_ids,
        )

    # 2) Build source text.
    source_text = _get_source_text(db, tenant_id=tenant_id, document_id=document_id, max_chars=max_source_chars)
    if not source_text.strip():
        return DocumentQAGenerateResult(mode="none", deleted=deleted, created=0, chunk_ids=[], preview=[])

    # 3) Generate Q/A pairs.
    mode, pairs = _generate_pairs(source_text, num_pairs=int(num_pairs), prefer_llm=bool(prefer_llm))

    if not pairs:
        return DocumentQAGenerateResult(mode=mode, deleted=deleted, created=0, chunk_ids=[], preview=[])

    next_index = _next_active_chunk_index(db, tenant_id=tenant_id, document_id=document_id, active_key=active_key)
    records, chunk_ids, chunk_metas = _build_qa_chunk_payloads(
        tenant_id=tenant_id,
        document_id=document_id,
        filename=getattr(document, "filename", ""),
        pairs=pairs,
        mode=mode,
        active_hash=active_hash,
        active_key=active_key,
        next_index=next_index,
    )
    source_label = str(getattr(document, "filename", "") or "document").strip()[:500] or "document"
    vector_ids = _index_qa_records(records, tenant_id=tenant_id, document_id=document_id)
    db_chunks = _persist_qa_chunks(
        db,
        tenant_id=tenant_id,
        document_id=document_id,
        records=records,
        chunk_ids=chunk_ids,
        chunk_metas=chunk_metas,
        vector_ids=vector_ids,
    )

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

    _update_document_chunk_stats(
        db,
        tenant_id=tenant_id,
        document_id=document_id,
        document=document,
        active_key=active_key,
    )

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


def _collect_active_qa_chunk_ids(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    active_key: str,
) -> list[UUID]:
    rows = (
        db.query(DocumentChunk.id, DocumentChunk.doc_metadata)
        .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
        .all()
    )
    qa_ids: list[UUID] = []
    for chunk_id, meta in rows:
        data = meta if isinstance(meta, dict) else {}
        if str(data.get("doc_pipeline_key") or "").strip() != active_key:
            continue
        if str(data.get("file_type") or "").strip().lower() != "qa":
            continue
        qa_ids.append(UUID(str(chunk_id)))
    return qa_ids


def _delete_existing_qa_chunks(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    qa_ids: list[UUID],
) -> int:
    if not qa_ids:
        return 0

    vector_store = get_vector_store()
    vector_errors = _delete_qa_vectors(
        vector_store,
        tenant_id=tenant_id,
        document_id=document_id,
        qa_ids=qa_ids,
    )
    bm25_errors = _delete_qa_bm25(tenant_id=tenant_id, qa_ids=qa_ids)
    _log_delete_errors(vector_errors=vector_errors, bm25_errors=bm25_errors)

    db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
        DocumentChunk.id.in_(qa_ids),
    ).delete(synchronize_session=False)
    db.commit()
    return len(qa_ids)


def _delete_qa_vectors(
    vector_store: Any,
    *,
    tenant_id: UUID,
    document_id: UUID,
    qa_ids: list[UUID],
) -> tuple[int, str | None]:
    error_count = 0
    first_error: str | None = None
    for chunk_id in qa_ids:
        try:
            vector_store.delete_by_document_id_and_filter(
                document_id=document_id,
                tenant_id=tenant_id,
                metadata_filter={"chunk_id": {"$eq": str(chunk_id)}},
            )
        except NotImplementedError:
            continue
        except Exception as exc:  # noqa: BLE001
            error_count += 1
            if first_error is None:
                first_error = str(exc)[:200]
    return error_count, first_error


def _delete_qa_bm25(*, tenant_id: UUID, qa_ids: list[UUID]) -> tuple[int, str | None]:
    error_count = 0
    first_error: str | None = None
    for chunk_id in qa_ids:
        try:
            hybrid_retriever.remove_from_bm25_index_by_metadata_filter(
                tenant_id=tenant_id,
                metadata_filter={"chunk_id": {"$eq": str(chunk_id)}},
            )
        except Exception as exc:  # noqa: BLE001
            error_count += 1
            if first_error is None:
                first_error = str(exc)[:200]
    return error_count, first_error


def _log_delete_errors(
    *,
    vector_errors: tuple[int, str | None],
    bm25_errors: tuple[int, str | None],
) -> None:
    vector_delete_errors, vector_delete_first_error = vector_errors
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

    bm25_delete_errors, bm25_delete_first_error = bm25_errors
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


def _next_active_chunk_index(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    active_key: str,
) -> int:
    query = db.query(func.max(DocumentChunk.chunk_index)).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
    )
    if active_key:
        query = query.filter(DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key)  # type: ignore[attr-defined]
    max_idx = query.scalar()
    return int(max_idx or -1) + 1


def _build_qa_chunk_payloads(
    *,
    tenant_id: UUID,
    document_id: UUID,
    filename: object,
    pairs: list[QAPair],
    mode: str,
    active_hash: str,
    active_key: str,
    next_index: int,
) -> tuple[list[dict[str, Any]], list[UUID], list[dict[str, Any]]]:
    source_label = str(filename or "document").strip()[:500] or "document"
    records: list[dict[str, Any]] = []
    chunk_ids: list[UUID] = []
    chunk_metas: list[dict[str, Any]] = []

    for pair in pairs:
        chunk_id = uuid.uuid4()
        meta = _build_qa_chunk_meta(
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_id=chunk_id,
            chunk_index=next_index,
            source_label=source_label,
            pair=pair,
            mode=mode,
            active_hash=active_hash,
            active_key=active_key,
        )
        content = f"Q: {pair.question.strip()}\nA: {pair.answer.strip()}".strip()
        records.append({"content": content, "metadata": meta})
        chunk_ids.append(chunk_id)
        chunk_metas.append(meta)
        next_index += 1

    return records, chunk_ids, chunk_metas


def _build_qa_chunk_meta(
    *,
    tenant_id: UUID,
    document_id: UUID,
    chunk_id: UUID,
    chunk_index: int,
    source_label: str,
    pair: QAPair,
    mode: str,
    active_hash: str,
    active_key: str,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "document_id": str(document_id),
        "chunk_id": str(chunk_id),
        "chunk_index": int(chunk_index),
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
    return meta


def _index_qa_records(
    records: list[dict[str, Any]],
    *,
    tenant_id: UUID,
    document_id: UUID,
) -> list[str | None]:
    vector_ids: list[str | None] = [None] * len(records)
    try:
        ids = list(get_vector_store().add_documents(records, document_id, tenant_id))
        for index, vector_id in enumerate(ids):
            if index >= len(vector_ids):
                break
            if vector_id:
                vector_ids[index] = str(vector_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            _DOCUMENT_QA_DEGRADED_LOG_MSG,
            "qa_vector_index",
            str(getattr(settings, "VECTOR_BACKEND", "") or "vector_store"),
            "index_failed",
            "check vector backend health/config; chunks saved but may not be retrievable via vectors",
            str(exc)[:200],
        )
    return vector_ids


def _persist_qa_chunks(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    records: list[dict[str, Any]],
    chunk_ids: list[UUID],
    chunk_metas: list[dict[str, Any]],
    vector_ids: list[str | None],
) -> list[DocumentChunk]:
    db_chunks: list[DocumentChunk] = []
    for index, chunk_id in enumerate(chunk_ids):
        chunk = DocumentChunk(
            id=chunk_id,
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_index=int(chunk_metas[index].get("chunk_index") or index),
            content=str(records[index].get("content") or ""),
            page_number=None,
            start_char=None,
            end_char=None,
            doc_metadata=chunk_metas[index],
            vector_id=vector_ids[index],
        )
        db_chunks.append(chunk)
        db.add(chunk)
    db.commit()
    return db_chunks


def _update_document_chunk_stats(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    document: DBDocument,
    active_key: str,
) -> None:
    try:
        stat_query = db.query(func.count(DocumentChunk.id), func.sum(func.length(DocumentChunk.content))).filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
        )
        if active_key:
            stat_query = stat_query.filter(DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key)  # type: ignore[attr-defined]
        count, total_chars = stat_query.first() or (None, None)
        document.chunk_count = int(count or 0)
        document.total_characters = int(total_chars or 0)
        db.commit()
    except Exception:
        db.rollback()


__all__ = [
    "DocumentQAGenerateResult",
    "QAPair",
    "extract_qa_pairs_from_text",
    "generate_and_index_document_qa",
]
