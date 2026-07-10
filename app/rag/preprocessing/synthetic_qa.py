
from typing import Any

from langchain_core.documents import Document

from app.rag.preprocessing.metadata_enrichment import build_document_metadata_enrichment

_SCHEMA = "mimirq.synthetic_qa_side_index.v1"


def build_synthetic_qa_side_index(
    *,
    text: str,
    metadata: dict[str, Any] | None = None,
    question_count: int = 3,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    enrichment = build_document_metadata_enrichment(
        text,
        metadata=meta,
        question_count=max(1, int(question_count or 1)),
    )
    merged = dict(meta)
    merged.update(enrichment)

    summary = str(merged.get("document_summary") or "").strip()
    questions = [str(item).strip() for item in (merged.get("document_questions") or []) if str(item).strip()]

    base_meta = {
        "document_id": merged.get("document_id"),
        "document_title": merged.get("document_title"),
        "synthetic_qa_schema": _SCHEMA,
    }

    documents: list[Document] = []
    if summary:
        documents.append(
            Document(
                page_content=summary,
                metadata={
                    **base_meta,
                    "side_index_kind": "summary",
                },
            )
        )

    for idx, question in enumerate(questions):
        documents.append(
            Document(
                page_content=question,
                metadata={
                    **base_meta,
                    "side_index_kind": "question",
                    "side_index_order": int(idx),
                },
            )
        )

    return {
        "schema": _SCHEMA,
        "summary": summary,
        "questions": questions,
        "documents": documents,
    }


__all__ = ["build_synthetic_qa_side_index"]
