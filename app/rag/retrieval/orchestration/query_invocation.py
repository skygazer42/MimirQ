from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.core.token_utils import num_tokens_from_string


@dataclass(frozen=True)
class RetrievalPerQueryItemInput:
    kind: str
    query: str
    elapsed_sec: float
    ok: bool
    retriever_debug: dict[str, Any] | None
    hop: int | None = None


@dataclass(frozen=True)
class QueryInvocationRecordInput:
    kind: str
    query: str
    docs: list[Document] | None
    error: str | None
    elapsed_sec: float
    retriever_debug: dict[str, Any] | None
    hop: int | None = None


@dataclass(frozen=True)
class QueryInvocationRecordOutput:
    per_query_item: dict[str, Any]
    error_entry: str | None
    kind: str
    docs: list[Document]


def build_retrieval_per_query_item(payload: RetrievalPerQueryItemInput) -> dict[str, Any]:
    kind = payload.kind.strip() or "main"
    out: dict[str, Any] = {
        "kind": kind,
        "query_chars": len(payload.query),
        "query_tokens": num_tokens_from_string(payload.query),
        "elapsed_sec": round(payload.elapsed_sec, 3),
        "ok": payload.ok,
        "retriever_debug": payload.retriever_debug,
    }
    if payload.hop is not None:
        out["hop"] = payload.hop
    return out


def format_retrieval_error(kind: str, error: str | None) -> str:
    normalized_kind = kind.strip() or "main"
    return f"{normalized_kind}:{(error if error is not None else '')[:160]}"


def build_query_invocation_record(payload: QueryInvocationRecordInput) -> QueryInvocationRecordOutput:
    kind = payload.kind.strip() or "main"
    return QueryInvocationRecordOutput(
        per_query_item=build_retrieval_per_query_item(
            RetrievalPerQueryItemInput(
                kind=kind,
                query=payload.query,
                elapsed_sec=payload.elapsed_sec,
                ok=payload.error is None,
                retriever_debug=payload.retriever_debug,
                hop=payload.hop,
            )
        ),
        error_entry=(format_retrieval_error(kind, payload.error) if payload.error else None),
        kind=kind,
        docs=list(payload.docs or []),
    )
