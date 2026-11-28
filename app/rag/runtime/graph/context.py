"""Prepare and render retrieved documents for generation."""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.tokens import num_tokens_from_string, truncate
from app.rag.retrieval.evidence.excerpts import extract_evidence_text
from app.services.tables.store_paths import parse_table_id
from app.types.document_metadata import metadata_text

logger = logging.getLogger("rag.pipelines.langgraph")

_ONTOLOGY_CONTEXT_INSTRUCTIONS = (
    "Evidence applies to its stated business object and source version. "
    "Co-mentions do not establish identity or a relation. "
    "Use the applicable policy and computed values. Missing observations do not prove absence."
    " Never estimate whole-table totals from partial rows. An action proposal is not an executed action."
    " Evaluate conditions using their declared fields and applicability. A workflow label does not override"
    " specific confirmation fields; do not invent additional prerequisites."
    " evaluation_reference_at is the rule evaluation time parameter, not a business event or fact change time."
    " Determine business chronology from the source attributes and their stated snapshot scope."
)
@dataclass(frozen=True)
class GroundedContext:
    text: str
    documents: list[Document]
    trace: dict[str, Any]


def _ontology_context_documents(context: dict[str, Any]) -> list[Document]:
    version = context["ontology_version_id"]
    documents = []
    for field, value in context.items():
        if field in {"ontology_version_id", "queries", "citations"} or not value:
            continue
        observations = value if field == "metrics" else [value]
        for index, observation in enumerate(observations):
            if field == "rule" and "observed_at" in observation:
                observation = {key: item for key, item in observation.items() if key != "observed_at"} | {
                    "evaluation_reference_at": observation["observed_at"]
                }
            metadata = {
                "source": f"Published ontology {field}",
                "ontology_evidence": True,
                "ontology_observation": True,
                "ontology_version_id": version,
                "ontology_kind": field,
                "evidence_record_id": f"{version}:{field}:{index}",
            }
            subject = observation
            if field == "rule":
                subject = observation["evidence"]
            elif field == "function":
                subject = observation["result"]
            if isinstance(subject, dict):
                for key in ("object_type", "asset_id"):
                    if key in subject:
                        metadata[key] = subject[key]
                if "asset_id" in subject:
                    table = parse_table_id(subject["asset_id"])
                    if table is not None:
                        metadata["document_id"] = str(table.document_id)
                if "key" in subject:
                    metadata["business_key"] = subject["key"]
            documents.append(
                Document(
                    page_content=json.dumps({"ontology_version_id": version, field: observation}, ensure_ascii=False),
                    metadata=metadata,
                )
            )
    return documents


def _context_provenance(doc: Document, origin: str) -> dict[str, Any]:
    metadata = doc.metadata
    record = {
        key: metadata[key] if key == "business_key" else str(metadata[key])
        for key in (
            "document_id",
            "chunk_id",
            "pipeline_hash",
            "ontology_version_id",
            "ontology_kind",
            "object_type",
            "business_key",
            "asset_id",
            "table_id",
        )
        if key in metadata and metadata[key] is not None
    }
    record["id"] = metadata.get("evidence_record_id") or doc.id or hashlib.sha256(doc.page_content.encode()).hexdigest()
    record["origin"] = origin
    return record


def build_grounded_context(
    docs: list[Document],
    *,
    ontology_context: dict[str, Any],
    query: str | None = None,
    kg_context: str = "",
) -> GroundedContext:
    """Allocate one context budget to original sources and complete ontology observations."""
    raw_docs = _prepare_context_docs([doc for doc in docs if not doc.metadata.get("ontology_evidence")], query=query)
    ontology_docs = [doc for doc in docs if doc.metadata.get("ontology_evidence")]
    ontology_docs.extend(_ontology_context_documents(ontology_context))
    if kg_context:
        ontology_docs.append(
            Document(
                page_content=kg_context,
                metadata={
                    "source": "KG Event Retrieval",
                    "ontology_observation": True,
                },
            )
        )

    max_tokens = max(0, int(settings.RAG_CONTEXT_MAX_TOTAL_TOKENS))
    limit = max_tokens or max(0, int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS))
    measure = num_tokens_from_string if max_tokens else len
    records = []
    candidates = []
    seen = set()
    for origin, documents in (("documents", raw_docs), ("ontology", ontology_docs)):
        for doc in documents:
            record = _context_provenance(doc, origin)
            identity = (
                doc.metadata.get("document_id"),
                doc.metadata.get("chunk_id"),
                doc.metadata.get("pipeline_hash"),
                doc.page_content,
            )
            record.update(in_context=False, reason="budget_exceeded")
            records.append(record)
            if identity in seen:
                record["reason"] = "duplicate"
                continue
            seen.add(identity)
            part = _build_context_part(
                doc,
                idx=len(candidates) + 1,
                query=query,
                max_per_chunk_chars=max(0, int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK)),
                max_per_chunk_tokens=max(0, int(settings.RAG_CONTEXT_MAX_TOKENS_PER_CHUNK)),
                include_provenance=True,
            )
            candidates.append((doc, part, record))

    selected = set()

    def render(indices: set[int]) -> str:
        return "\n\n".join(
            [
                _ONTOLOGY_CONTEXT_INSTRUCTIONS,
                *[part for index, (_doc, part, _record) in enumerate(candidates) if index in indices],
            ]
        )

    available = max(0, limit - measure(_ONTOLOGY_CONTEXT_INSTRUCTIONS)) if limit else 0
    groups = {record["origin"] for _doc, _part, record in candidates}
    # Reserve an initial share for each channel, then redistribute unused space.
    shares = {origin: available // len(groups) for origin in groups}
    for origin in ("documents", "ontology"):
        group_size = 0
        for index, (_doc, part, record) in enumerate(candidates):
            if record["origin"] != origin:
                continue
            size = measure("\n\n" + part)
            if limit and (group_size + size > shares[origin] or measure(render(selected | {index})) > limit):
                continue
            selected.add(index)
            group_size += size
    for index in range(len(candidates)):
        if not limit or measure(render(selected | {index})) <= limit:
            selected.add(index)

    source_ids = {
        str(candidates[index][0].metadata["document_id"])
        for index in selected
        if candidates[index][0].metadata.get("document_id")
        and not candidates[index][0].metadata.get("ontology_observation")
    }
    for index in list(selected):
        doc, _part, record = candidates[index]
        required = set(doc.metadata.get("ontology_policy_sources", []))
        if required - source_ids:
            selected.remove(index)
            record["reason"] = "policy_source_not_selected"
    for index in selected:
        candidates[index][2].update(in_context=True, reason="selected")
    text = render(selected) if selected else ""
    return GroundedContext(
        text=text,
        documents=[doc for index, (doc, _part, _record) in enumerate(candidates) if index in selected],
        trace={
            "limit": limit,
            "unit": "tokens" if max_tokens else "characters",
            "used": measure(text),
            "records": records,
        },
    )


def _build_context(docs: list[Document], *, query: str | None = None) -> str:
    """Format retrieved document context."""
    if not docs:
        return "No relevant reference materials found."

    usable_docs = _prepare_context_docs(docs, query=query)

    parts = []
    max_per_chunk_chars = max(0, int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK))
    max_total_chars = max(0, int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS))
    max_per_chunk_tokens = max(0, int(settings.RAG_CONTEXT_MAX_TOKENS_PER_CHUNK))
    max_total_tokens = max(0, int(settings.RAG_CONTEXT_MAX_TOTAL_TOKENS))
    total_limit = max_total_tokens or max_total_chars
    measure = num_tokens_from_string if max_total_tokens else len
    total_size = 0
    for idx, doc in enumerate(usable_docs, 1):
        part = _build_context_part(
            doc,
            idx=idx,
            query=query,
            max_per_chunk_chars=max_per_chunk_chars,
            max_per_chunk_tokens=max_per_chunk_tokens,
        )
        part_size = measure(part)
        if total_limit and parts and total_size + part_size > total_limit:
            break
        parts.append(part)
        total_size += part_size
        if not max_total_tokens and max_total_chars and total_size >= max_total_chars:
            break
    return "\n\n".join(parts)


def _prepare_context_docs(docs: list[Document], *, query: str | None) -> list[Document]:
    usable_docs = _denoise_context_docs(docs)
    if settings.RAG_CONTEXT_LLM_COMPRESSION_ENABLED:
        return _compress_context_docs_with_llm(usable_docs, query=query)
    if settings.RAG_CONTEXT_COMPRESSION_ENABLED:
        usable_docs = _compress_context_docs(usable_docs, query=query)
    if settings.RAG_CONTEXT_REORDER_ENABLED:
        usable_docs = _reorder_context_docs(usable_docs)
    return usable_docs


def _denoise_context_docs(docs: list[Document]) -> list[Document]:
    try:
        from app.rag.runtime.context import denoise_context_docs

        return denoise_context_docs(docs)
    except Exception as exc:
        logger.debug("Context denoise failed, falling back to raw docs: %s", exc)
        return list(docs)


def _compress_context_docs_with_llm(docs: list[Document], *, query: str | None) -> list[Document]:
    try:
        from app.rag.llm.context_compression import compress_context_docs_with_llm

        return compress_context_docs_with_llm(docs, query=query)
    except Exception as exc:
        logger.debug("LLM context compression failed, skipping compression: %s", exc)
        return list(docs)


def _compress_context_docs(docs: list[Document], *, query: str | None) -> list[Document]:
    try:
        from app.rag.runtime.context import compress_context_docs

        return compress_context_docs(docs, query=query)
    except Exception as exc:
        logger.debug("Context compression failed, skipping compression: %s", exc)
        return list(docs)


def _reorder_context_docs(docs: list[Document]) -> list[Document]:
    try:
        from app.rag.runtime.context import reorder_docs_for_generation

        return reorder_docs_for_generation(docs)
    except Exception as exc:
        logger.debug("Context doc ordering failed, skipping reorder: %s", exc)
        return list(docs)


def _context_page_info(meta: dict[str, Any]) -> str | None:
    try:
        page_raw = meta.get("page")
        page_int = int(page_raw) if page_raw is not None else None
    except (OverflowError, TypeError, ValueError):
        return None
    if page_int and page_int > 0:
        return f"Page {page_int}"
    return None


def _context_role_info(meta: dict[str, Any]) -> str | None:
    retrieval_role = meta.get("retrieval_role")
    if retrieval_role == "neighbor":
        return "neighbor"
    if retrieval_role:
        return str(retrieval_role)
    return None


def _context_content(
    doc: Document,
    *,
    query: str | None,
    max_per_chunk_chars: int,
    max_per_chunk_tokens: int,
) -> str:
    raw_content = doc.page_content.strip()
    if doc.metadata.get("ontology_observation"):
        return raw_content
    if settings.RAG_CONTEXT_EVIDENCE_ENABLED and query:
        return extract_evidence_text(
            raw_content,
            str(query),
            max_chars=(max_per_chunk_chars if not max_per_chunk_tokens else 0),
            max_sentences=settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK,
            min_sentence_chars=settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS,
        )
    if max_per_chunk_tokens:
        return truncate(raw_content, max_per_chunk_tokens)
    if max_per_chunk_chars and len(raw_content) > max_per_chunk_chars:
        return raw_content[:max_per_chunk_chars] + "..."
    return raw_content


def _build_context_part(
    doc: Document,
    *,
    idx: int,
    query: str | None,
    max_per_chunk_chars: int,
    max_per_chunk_tokens: int,
    include_provenance: bool = False,
) -> str:
    meta = doc.metadata
    filename = metadata_text(meta, "filename")
    source = str(meta.get("source") or filename or "Unknown")
    info_parts: list[str] = []
    title = metadata_text(meta, "document_title") or metadata_text(meta, "doc_title") or metadata_text(meta, "title")
    if title:
        info_parts.append(f"Title: {title}")
    if filename:
        info_parts.append(f"File: {filename}")
    elif source:
        info_parts.append(source)
    for value in (
        _context_page_info(meta),
        meta.get("header_path") or meta.get("header_context"),
        _context_role_info(meta),
    ):
        if value:
            info_parts.append(str(value))
    if include_provenance:
        origin = "ontology" if meta.get("ontology_evidence") else "documents"
        info_parts.append("Provenance " + json.dumps(_context_provenance(doc, origin), ensure_ascii=False))
    content = _context_content(
        doc,
        query=query,
        max_per_chunk_chars=max_per_chunk_chars,
        max_per_chunk_tokens=max_per_chunk_tokens,
    )
    return f"[Source {idx}: {' | '.join(info_parts)}]\n{content}"
