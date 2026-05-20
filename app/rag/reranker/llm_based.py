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
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.models.chunk import Document
from app.rag.core.http import httpx_trust_env
from app.rag.reranker.base import DocumentReranker


@dataclass
class LLMRerankResult:
    """LLM rerank result."""
    ordered_ids: list[str]
    score_map: dict[str, float]
    elapsed_sec: float
    model_used: str | None


def _build_http_clients() -> tuple[httpx.Client, httpx.AsyncClient]:
    """
    Reuse the same proxy handling as the RAG engine:
    - If a SOCKS proxy is detected, disable trust_env to avoid httpx issues.
    """
    trust_env = httpx_trust_env()
    return httpx.Client(trust_env=trust_env, timeout=settings.LLM_TIMEOUT), httpx.AsyncClient(
        trust_env=trust_env, timeout=settings.LLM_TIMEOUT
    )


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
    except Exception:
        return None
    return max(min(i, max_value), min_value)


def _clamp_score(value: Any, *, default: float = 0.0) -> float:
    try:
        score = float(value)
    except Exception:
        score = float(default)
    return max(0.0, min(score, 1.0))


def _sanitize_structure(structure: Any) -> dict[str, Any] | None:
    if not isinstance(structure, dict):
        return None

    out: dict[str, Any] = {}

    list_info = structure.get("list")
    if isinstance(list_info, dict):
        item_count = _clamp_int(list_info.get("item_count"), min_value=0, max_value=10_000)
        min_level = _clamp_int(list_info.get("min_level"), min_value=0, max_value=50)
        max_level = _clamp_int(list_info.get("max_level"), min_value=0, max_value=50)
        list_out: dict[str, Any] = {}
        if item_count is not None:
            list_out["item_count"] = item_count
        if min_level is not None:
            list_out["min_level"] = min_level
        if max_level is not None:
            list_out["max_level"] = max_level
        if list_out:
            out["list"] = list_out

    table_info = structure.get("table")
    if isinstance(table_info, dict):
        table_out: dict[str, Any] = {}
        title = table_info.get("title")
        if isinstance(title, str) and title.strip():
            table_out["title"] = title.strip()[:200]
        sheet_name = table_info.get("sheet_name")
        if isinstance(sheet_name, str) and sheet_name.strip():
            table_out["sheet_name"] = sheet_name.strip()[:200]
        if table_out:
            out["table"] = table_out

    return out or None


def _build_candidate_payload(*, cid: str, text: str, meta: dict[str, Any] | None, max_chars: int) -> dict[str, Any] | None:
    cid_norm = str(cid or "").strip()
    text_norm = str(text or "").strip()
    if not cid_norm or not text_norm:
        return None

    if max_chars and len(text_norm) > max_chars:
        text_norm = text_norm[:max_chars] + "..."

    payload: dict[str, Any] = {"id": cid_norm, "text": text_norm}

    header_path = (meta or {}).get("header_path")
    if isinstance(header_path, str) and header_path.strip():
        payload["header_path"] = header_path.strip()[:200]

    semantic_role = (meta or {}).get("chunk_semantic_role")
    if isinstance(semantic_role, str) and semantic_role.strip():
        payload["chunk_semantic_role"] = semantic_role.strip()[:40]

    structure = (meta or {}).get("structure")
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
    else:
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        source = dict(parsed) if isinstance(parsed, dict) else {}

    out: dict[str, float] = {}
    for key, value in source.items():
        name = str(key or "").strip()
        if not name:
            continue
        out[name.casefold()] = _clamp_score(value, default=0.7)
    return out


def resolve_llm_reranker_weight(*, tenant_id: str | None, query_type: str | None) -> float:
    tenant_map = _load_weight_mapping(getattr(settings, "RERANKER_LLM_WEIGHT_BY_TENANT", ""))
    query_type_map = _load_weight_mapping(getattr(settings, "RERANKER_LLM_WEIGHT_BY_QUERY_TYPE", ""))

    tenant_key = str(tenant_id or "").strip().casefold()
    if tenant_key and tenant_key in tenant_map:
        return float(tenant_map[tenant_key])

    query_type_key = str(query_type or "").strip().casefold()
    if query_type_key and query_type_key in query_type_map:
        return float(query_type_map[query_type_key])

    return _clamp_score(getattr(settings, "RERANKER_LLM_WEIGHT", 0.7), default=0.7)


def _finalize_rerank_scores(
    *,
    candidates: list[dict[str, Any]],
    llm_scores: dict[str, float],
    llm_weight: float,
    fallback_score: float = 0.0,
) -> tuple[list[str], dict[str, float]]:
    weight = _clamp_score(llm_weight, default=0.7)
    vector_weight = max(0.0, min(1.0, 1.0 - weight))
    fallback = _clamp_score(fallback_score, default=0.0)
    llm_scores_present = bool(llm_scores)

    ranked: list[tuple[str, float]] = []
    score_map: dict[str, float] = {}
    seen: set[str] = set()
    for candidate in candidates:
        cid = str(candidate.get("id") or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)

        vector_score = _vector_anchor_score(candidate)
        if cid in llm_scores:
            final_score = round(
                weight * _clamp_score(llm_scores.get(cid), default=0.0) + vector_weight * vector_score,
                4,
            )
        elif not llm_scores_present:
            final_score = round(vector_score, 4)
        else:
            final_score = round(weight * fallback + vector_weight * vector_score, 4)
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
        http_client, http_async_client = _build_http_clients()

        self.model_used = model_name
        self.llm_weight = resolve_llm_reranker_weight(tenant_id=None, query_type=None)
        self.fallback_score = _clamp_score(getattr(settings, "RERANKER_LLM_FALLBACK_SCORE", 0.5), default=0.5)
        self._llm = ChatOpenAI(
            model=model_name,
            api_key=settings.LLM_API_KEY,
            base_url=normalize_openai_compatible_base_url(settings.LLM_API_BASE),
            temperature=float(settings.RERANKER_TEMPERATURE or 0.0),
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

        candidates: list[dict[str, Any]] = []
        id_to_doc: dict[str, Document] = {}
        for idx, doc in enumerate(documents):
            text = (doc.page_content or "").strip()
            if not text:
                continue
            cid = self._candidate_id(doc, idx)
            meta = doc.metadata or {}
            candidates.append(
                {
                    "id": cid,
                    "text": text,
                    "header_path": meta.get("header_path"),
                    "structure": meta.get("structure"),
                }
            )
            id_to_doc[cid] = doc

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
        for cid in result.ordered_ids:
            doc = id_to_doc.get(cid)
            if not doc or cid in used:
                continue
            used.add(cid)
            if doc.metadata is None:
                doc.metadata = {}
            if cid in result.score_map:
                doc.metadata["score"] = float(result.score_map[cid])
            if score_threshold is not None:
                score = doc.metadata.get("score")
                if score is not None and float(score) < score_threshold:
                    continue
            ordered.append(doc)
            if top_n and len(ordered) >= top_n:
                return ordered

        # Append documents that were not reranked.
        for idx, doc in enumerate(documents):
            cid = self._candidate_id(doc, idx)
            if cid in used:
                continue
            if score_threshold is not None:
                score = (doc.metadata or {}).get("score")
                if score is not None and float(score) < score_threshold:
                    continue
            ordered.append(doc)
            if top_n and len(ordered) >= top_n:
                break

        return ordered

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
        payload: list[dict[str, Any]] = []
        prompt_payload: list[dict[str, Any]] = []
        effective_weight = (
            _clamp_score(llm_weight, default=0.7)
            if llm_weight is not None
            else resolve_llm_reranker_weight(tenant_id=tenant_id, query_type=query_type)
        )
        effective_fallback = (
            _clamp_score(fallback_score, default=0.5)
            if fallback_score is not None
            else _clamp_score(getattr(self, "fallback_score", getattr(settings, "RERANKER_LLM_FALLBACK_SCORE", 0.5)), default=0.5)
        )
        max_chars = int(settings.RERANKER_MAX_CHARS or 800)
        for c in candidates:
            cid = str(c.get("id") or "").strip()
            text = (c.get("text") or "").strip()
            item = _build_candidate_payload(cid=cid, text=text, meta=c, max_chars=max_chars)
            if item is not None:
                prompt_payload.append(item)
                scored_item = dict(item)
                scored_item["vector_score"] = _vector_anchor_score(c)
                payload.append(scored_item)

        if not payload:
            return LLMRerankResult(ordered_ids=[], score_map={}, elapsed_sec=0.0, model_used=self.model_used)

        start = time.time()
        out_text = self._chain.invoke(
            {
                "query": query,
                "candidates": json.dumps(prompt_payload, ensure_ascii=False),
            }
        )
        elapsed = time.time() - start

        json_text = _extract_json_array((out_text or "").strip())
        if not json_text:
            ordered, score_map = _finalize_rerank_scores(
                candidates=payload,
                llm_scores={},
                llm_weight=effective_weight,
                fallback_score=0.0,
            )
            return LLMRerankResult(ordered_ids=ordered, score_map=score_map, elapsed_sec=elapsed, model_used=self.model_used)

        try:
            data = json.loads(json_text)
        except Exception:
            ordered, score_map = _finalize_rerank_scores(
                candidates=payload,
                llm_scores={},
                llm_weight=effective_weight,
                fallback_score=0.0,
            )
            return LLMRerankResult(ordered_ids=ordered, score_map=score_map, elapsed_sec=elapsed, model_used=self.model_used)

        llm_scores: dict[str, float] = {}
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or "").strip()
            if not cid:
                continue
            llm_scores[cid] = _clamp_score(item.get("score", 0.0), default=0.0)

        ordered, score_map = _finalize_rerank_scores(
            candidates=payload,
            llm_scores=llm_scores,
            llm_weight=effective_weight,
            fallback_score=effective_fallback,
        )
        return LLMRerankResult(ordered_ids=ordered, score_map=score_map, elapsed_sec=elapsed, model_used=self.model_used)


_llm_reranker: LLMReranker | None = None


def get_llm_reranker() -> LLMReranker:
    """Get the LLM reranker singleton."""
    global _llm_reranker
    if _llm_reranker is None:
        _llm_reranker = LLMReranker()
    return _llm_reranker
