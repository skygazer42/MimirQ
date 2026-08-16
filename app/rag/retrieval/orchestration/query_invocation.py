
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
    out: dict[str, Any] = {
        "kind": str(payload.kind or "").strip() or "main",
        "query_chars": len(payload.query or ""),
        "query_tokens": num_tokens_from_string(payload.query or ""),
        "elapsed_sec": round(float(payload.elapsed_sec or 0.0), 3),
        "ok": bool(payload.ok),
        "retriever_debug": payload.retriever_debug,
    }
    if payload.hop is not None:
        out["hop"] = int(payload.hop)
    return out


def format_retrieval_error(kind: str, error: str | None) -> str:
    return f"{str(kind or '').strip() or 'main'}:{str(error or '')[:160]}"


def build_query_invocation_record(payload: QueryInvocationRecordInput) -> QueryInvocationRecordOutput:
    kind = str(payload.kind or "").strip() or "main"
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
