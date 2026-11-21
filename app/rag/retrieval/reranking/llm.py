"""
LLM-based reranker.

Reranks retrieved candidates to improve reference relevance.

Strategy:
- Input query + candidates (truncated text)
- Ask the LLM to output strict JSON: [{"id": "...", "score": 0~1}, ...], sorted by relevance
- Fall back to original order if parsing fails

Note: this module is a reranker implementation; do not confuse it with app.rag.llm (LLM client).
"""

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.infrastructure.config import settings
from app.infrastructure.http.client import get_http_client_pool
from app.infrastructure.http.openai import normalize_openai_compatible_base_url
from app.rag.retrieval.reranking.base import DocumentReranker
from app.types.document_metadata import metadata_text
from app.types.rag_document import Document


@dataclass
class LLMRerankResult:
    """LLM rerank result."""

    ordered_ids: list[str]
    score_map: dict[str, float]
    elapsed_sec: float
    model_used: str | None


def _extract_json_array(text: str) -> str | None:
    """Best-effort extract the JSON array portion from LLM output."""
    if not text:
        return None
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _clamp_int(value: Any, *, min_value: int, max_value: int) -> int | None:
    try:
        i = int(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return max(min(i, max_value), min_value)


def _clamp_score(value: Any, *, default: float = 0.0) -> float:
    try:
        score = float(value)
    except (OverflowError, TypeError, ValueError):
        score = float(default)
    return max(0.0, min(score, 1.0))


def _sanitize_list_structure(list_info: Any) -> dict[str, Any] | None:
    if not isinstance(list_info, dict):
        return None
    list_out: dict[str, Any] = {}
    for key, maximum in (("item_count", 10_000), ("min_level", 50), ("max_level", 50)):
        value = _clamp_int(list_info.get(key), min_value=0, max_value=maximum)
        if value is not None:
            list_out[key] = value
    return list_out


def _sanitize_table_structure(table_info: Any) -> dict[str, Any] | None:
    if not isinstance(table_info, dict):
        return None
    table_out: dict[str, Any] = {}
    for key in ("title", "sheet_name"):
        value = table_info.get(key)
        if isinstance(value, str) and value.strip():
            table_out[key] = value.strip()[:200]
    return table_out


def _sanitize_structure(structure: Any) -> dict[str, Any] | None:
    if not isinstance(structure, dict):
        return None

    out: dict[str, Any] = {}
    list_out = _sanitize_list_structure(structure.get("list"))
    table_out = _sanitize_table_structure(structure.get("table"))
    if list_out:
        out["list"] = list_out
    if table_out:
        out["table"] = table_out

    return out


def _prepare_llm_candidates(
    reranker: "LLMReranker", documents: list[Document]
) -> tuple[list[dict[str, Any]], dict[str, Document]]:
    candidates: list[dict[str, Any]] = []
    id_to_doc: dict[str, Document] = {}
    for idx, doc in enumerate(documents):
        text = (doc.page_content).strip()
        if not text:
            continue
        cid = reranker._candidate_id(doc, idx)
        meta = doc.metadata or {}
        candidate = {
            "id": cid,
            "text": text,
            "header_path": meta.get("header_path"),
            "structure": meta.get("structure"),
        }
        for key in ("vector_score", "score", "distance"):
            if key in meta:
                candidate[key] = meta[key]
        candidates.append(candidate)
        id_to_doc[cid] = doc
    return candidates, id_to_doc


def _document_meets_threshold(doc: Document, score_threshold: float | None) -> bool:
    if score_threshold is None:
        return True
    score = (doc.metadata or {}).get("score")
    return score is None or float(score) >= score_threshold


def _append_ranked_documents(
    *,
    ordered: list[Document],
    used: set[str],
    ordered_ids: list[str],
    id_to_doc: dict[str, Document],
    score_map: dict[str, float],
    score_threshold: float | None,
    top_n: int | None,
) -> list[Document] | None:
    for cid in ordered_ids:
        doc = id_to_doc.get(cid)
        if not doc or cid in used:
            continue
        used.add(cid)
        if cid in score_map:
            doc.metadata["score"] = float(score_map[cid])
        if not _document_meets_threshold(doc, score_threshold):
            continue
        ordered.append(doc)
        if top_n and len(ordered) >= top_n:
            return ordered
    return None


def _append_unreranked_documents(
    *,
    ordered: list[Document],
    used: set[str],
    documents: list[Document],
    reranker: "LLMReranker",
    score_threshold: float | None,
    top_n: int | None,
) -> list[Document]:
    for idx, doc in enumerate(documents):
        cid = reranker._candidate_id(doc, idx)
        if cid in used or not _document_meets_threshold(doc, score_threshold):
            continue
        ordered.append(doc)
        if top_n and len(ordered) >= top_n:
            break
    return ordered


def _build_candidate_payload(*, cid: str, text: str, meta: dict[str, Any], max_chars: int) -> dict[str, Any] | None:
    if not cid or not text:
        return None

    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "..."

    payload: dict[str, Any] = {"id": cid, "text": text}

    header_path = meta.get("header_path")
    if isinstance(header_path, str) and header_path.strip():
        payload["header_path"] = header_path.strip()[:200]

    semantic_role = meta.get("chunk_semantic_role")
    if isinstance(semantic_role, str) and semantic_role.strip():
        payload["chunk_semantic_role"] = semantic_role.strip()[:40]

    structure = meta.get("structure")
    structure_sanitized = _sanitize_structure(structure)
    if structure_sanitized:
        payload["structure"] = structure_sanitized

    return payload


def _vector_anchor_score(candidate: dict[str, Any]) -> float:
    for key in ("vector_score", "score", "distance"):
        if key in candidate:
            return _clamp_score(candidate.get(key), default=0.0)
    return 0.0


def _load_weight_mapping(raw: Any) -> dict[str, float]:
    if isinstance(raw, dict):
        source = dict(raw)
    elif raw is None:
        return {}
    else:
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        source = dict(parsed) if isinstance(parsed, dict) else {}

    out: dict[str, float] = {}
    for key, value in source.items():
        name = key.strip()
        if not name:
            continue
        out[name.casefold()] = _clamp_score(value, default=0.7)
    return out


def resolve_llm_reranker_weight(*, tenant_id: str | None, query_type: str | None) -> float:
    tenant_map = _load_weight_mapping(settings.RERANKER_LLM_WEIGHT_BY_TENANT)
    query_type_map = _load_weight_mapping(settings.RERANKER_LLM_WEIGHT_BY_QUERY_TYPE)

    tenant_key = tenant_id.strip().casefold() if tenant_id is not None else None
    if tenant_key and tenant_key in tenant_map:
        return tenant_map[tenant_key]

    query_type_key = query_type.strip().casefold() if query_type is not None else None
    if query_type_key and query_type_key in query_type_map:
        return query_type_map[query_type_key]

    return _clamp_score(settings.RERANKER_LLM_WEIGHT, default=0.7)


def _finalize_rerank_scores(
    *,
    candidates: list[tuple[str, float]],
    llm_scores: dict[str, float],
    llm_weight: float,
    fallback_score: float = 0.0,
) -> tuple[list[str], dict[str, float]]:
    vector_weight = 1.0 - llm_weight
    llm_scores_present = bool(llm_scores)

    ranked: list[tuple[str, float]] = []
    score_map: dict[str, float] = {}
    for cid, vector_score in candidates:
        if cid in score_map:
            continue

        if cid in llm_scores:
            final_score = round(
                llm_weight * llm_scores[cid] + vector_weight * vector_score,
                4,
            )
        elif not llm_scores_present:
            final_score = round(vector_score, 4)
        else:
            final_score = round(llm_weight * fallback_score + vector_weight * vector_score, 4)
        score_map[cid] = final_score
        ranked.append((cid, final_score))

    ranked.sort(key=lambda item: (-item[1], item[0]))
    return [cid for cid, _score in ranked], score_map


class LLMReranker(DocumentReranker):
    """LLM reranker (document-level reranking via LLM)."""

    def __init__(self) -> None:
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI

        model_name = settings.RERANKER_MODEL or settings.LLM_MODEL_FAST or settings.LLM_MODEL
        # The process pool owns these clients and closes them at application shutdown.
        pool = get_http_client_pool()
        http_client = pool.get_external_sync_client()
        http_async_client = pool.get_external_async_client()

        self.model_used = model_name
        self.llm_weight = resolve_llm_reranker_weight(tenant_id=None, query_type=None)
        self.fallback_score = _clamp_score(settings.RERANKER_LLM_FALLBACK_SCORE, default=0.5)
        self._llm = ChatOpenAI(
            model=model_name,
            api_key=settings.LLM_API_KEY,
            base_url=normalize_openai_compatible_base_url(settings.LLM_API_BASE),
            temperature=float(settings.RERANKER_TEMPERATURE),
            streaming=False,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            http_client=http_client,
            http_async_client=http_async_client,
        )

        self._prompt = ChatPromptTemplate.from_template(
            """You are a "retrieval result reranker". Given query and candidate passages, output strict JSON array:
[{{"id": "...", "score": 0.0}}]

Requirements:
1) score ranges 0~1, higher means more relevant;
2) sort by score from high to low;
3) only output JSON, no explanations, Markdown, or code blocks;
4) id must come from input candidates (do not add/fabricate id).

query: {query}

candidates(JSON): {candidates}
"""
        )
        self._chain = self._prompt | self._llm | StrOutputParser()

    def _candidate_id(self, document: Document, fallback_idx: int) -> str:
        """Extract a candidate ID from a Document."""
        meta = document.metadata or {}
        for key in ("candidate_id", "doc_id", "chunk_id"):
            value = meta.get(key)
            if value:
                return str(value)
        doc_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        if doc_id is not None and chunk_index is not None:
            return f"{doc_id}:{chunk_index}"
        return f"idx:{fallback_idx}"

    def _rerank_run_options(self, options: dict[str, Any]) -> dict[str, Any]:
        return {
            "tenant_id": metadata_text(options, "tenant_id"),
            "query_type": options.get("query_type"),
        }

    def run(
        self,
        query: str,
        documents: list[Document],
        score_threshold: float | None = None,
        top_n: int | None = None,
        user: str | None = None,
        *,
        tenant_id: str | None = None,
        query_type: str | None = None,
    ) -> list[Document]:
        """
        Run LLM reranking.

        Args:
            query: query text
            documents: document list
            score_threshold: score threshold
            top_n: return top N results
            user: user identifier (unused)

        Returns:
            reranked document list
        """
        if not documents:
            return []

        candidates, id_to_doc = _prepare_llm_candidates(self, documents)
        if not candidates:
            return documents[:top_n] if top_n else documents

        result = self.rerank_raw(
            query=query,
            candidates=candidates,
            llm_weight=resolve_llm_reranker_weight(tenant_id=tenant_id, query_type=query_type),
            fallback_score=self.fallback_score,
            tenant_id=tenant_id,
            query_type=query_type,
        )
        if not result.ordered_ids:
            return documents[:top_n] if top_n else documents

        ordered: list[Document] = []
        used: set[str] = set()
        ranked = _append_ranked_documents(
            ordered=ordered,
            used=used,
            ordered_ids=result.ordered_ids,
            id_to_doc=id_to_doc,
            score_map=result.score_map,
            score_threshold=score_threshold,
            top_n=top_n,
        )
        if ranked is not None:
            return ranked
        return _append_unreranked_documents(
            ordered=ordered,
            used=used,
            documents=documents,
            reranker=self,
            score_threshold=score_threshold,
            top_n=top_n,
        )

    def rerank_raw(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        llm_weight: float | None = None,
        fallback_score: float | None = None,
        tenant_id: str | None = None,
        query_type: str | None = None,
    ) -> LLMRerankResult:
        """
        Call the LLM directly for reranking (raw interface).

        Args:
            query: query text
            candidates: candidate list [{id, text, ...}]

        Returns:
            LLMRerankResult with ordered IDs and score map
        """
        scored_candidates: list[tuple[str, float]] = []
        prompt_payload: list[dict[str, Any]] = []
        effective_weight = (
            _clamp_score(llm_weight, default=0.7)
            if llm_weight is not None
            else resolve_llm_reranker_weight(tenant_id=tenant_id, query_type=query_type)
        )
        effective_fallback = (
            _clamp_score(fallback_score, default=0.5)
            if fallback_score is not None
            else _clamp_score(self.fallback_score, default=0.5)
        )
        max_chars = int(settings.RERANKER_MAX_CHARS)
        for c in candidates:
            cid = c["id"].strip()
            text = c["text"].strip()
            item = _build_candidate_payload(cid=cid, text=text, meta=c, max_chars=max_chars)
            if item is not None:
                prompt_payload.append(item)
                scored_candidates.append((cid, _vector_anchor_score(c)))

        if not scored_candidates:
            return LLMRerankResult(ordered_ids=[], score_map={}, elapsed_sec=0.0, model_used=self.model_used)

        start = time.time()
        out_text = self._chain.invoke(
            {
                "query": query,
                "candidates": json.dumps(prompt_payload, ensure_ascii=False),
            }
        )
        elapsed = time.time() - start

        json_text = _extract_json_array(out_text.strip())
        data = []
        if json_text:
            try:
                data = json.loads(json_text)
            except json.JSONDecodeError:
                # Malformed model output keeps the existing vector-only fallback.
                data = []
        llm_scores: dict[str, float] = {}
        payload_ids = {cid for cid, _ in scored_candidates}
        for item in data:
            if not isinstance(item, dict):
                continue
            cid = metadata_text(item, "id")
            if not cid or cid not in payload_ids:
                continue
            llm_scores[cid] = _clamp_score(item.get("score", 0.0), default=0.0)

        ordered, score_map = _finalize_rerank_scores(
            candidates=scored_candidates,
            llm_scores=llm_scores,
            llm_weight=effective_weight,
            fallback_score=effective_fallback,
        )
        return LLMRerankResult(
            ordered_ids=ordered, score_map=score_map, elapsed_sec=elapsed, model_used=self.model_used
        )


_llm_reranker: LLMReranker | None = None
_llm_reranker_lock = threading.Lock()


def get_llm_reranker() -> LLMReranker:
    """Get the process-local LLM reranker without duplicate concurrent construction."""
    global _llm_reranker
    with _llm_reranker_lock:
        if _llm_reranker is None:
            _llm_reranker = LLMReranker()
        return _llm_reranker


def reset_llm_reranker() -> None:
    """Forget the cached model before its borrowed HTTP pool closes."""
    global _llm_reranker
    with _llm_reranker_lock:
        _llm_reranker = None
