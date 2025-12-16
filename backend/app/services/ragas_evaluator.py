"""
RAGAS evaluation service.

- Supports conversation-based evaluation using stored chat messages + citations.
- Runs in FastAPI BackgroundTasks (sync function).
"""

from __future__ import annotations

import math
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

import httpx

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.chat import Conversation, Message
from app.models.document import DocumentChunk
from app.models.evaluation import RagasEvaluationItem, RagasEvaluationRun
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids


def _build_http_clients() -> tuple[httpx.Client, httpx.AsyncClient]:
    """
    Reuse the same proxy-handling logic as the RAG engine:
    - If a SOCKS proxy is detected, disable trust_env to avoid httpx issues.
    """
    proxy_candidates = [
        os.getenv("OPENAI_PROXY"),
        os.getenv("HTTPS_PROXY"),
        os.getenv("HTTP_PROXY"),
        os.getenv("ALL_PROXY"),
        os.getenv("https_proxy"),
        os.getenv("http_proxy"),
        os.getenv("all_proxy"),
    ]
    proxies = [p for p in proxy_candidates if p]
    trust_env = True
    socks_proxy = next((p for p in proxies if p.lower().startswith("socks")), None)
    if socks_proxy:
        trust_env = False
    return httpx.Client(trust_env=trust_env), httpx.AsyncClient(trust_env=trust_env)


def _pair_turns(messages: List[Message]) -> List[Tuple[Message, Message]]:
    """
    Pair user -> assistant messages in order.
    Keeps the latest user message before an assistant reply.
    """
    turns: List[Tuple[Message, Message]] = []
    pending_user: Optional[Message] = None
    for msg in messages:
        if msg.role == "user":
            pending_user = msg
            continue
        if msg.role == "assistant":
            if pending_user is None:
                continue
            turns.append((pending_user, msg))
            pending_user = None
    return turns


def _extract_contexts(
    *,
    db,
    tenant_id: UUID,
    allowed_document_ids: List[UUID],
    citations: Any,
    max_context_chars: int = 4000,
) -> List[str]:
    """
    Resolve full chunk contents from stored citations.
    """
    if not citations:
        return []

    chunk_ids: List[UUID] = []
    seen: set[UUID] = set()
    for item in citations:
        raw = None
        if isinstance(item, dict):
            raw = item.get("chunk_id")
        if not raw:
            continue
        try:
            cid = UUID(str(raw))
        except Exception:
            continue
        if cid in seen:
            continue
        seen.add(cid)
        chunk_ids.append(cid)

    if not chunk_ids:
        return []

    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.id.in_(chunk_ids),
        )
        .all()
    )
    chunk_map: Dict[UUID, DocumentChunk] = {c.id: c for c in chunks}

    contexts: List[str] = []
    for cid in chunk_ids:
        chunk = chunk_map.get(cid)
        if not chunk:
            continue
        if allowed_document_ids and chunk.document_id not in set(allowed_document_ids):
            continue
        content = chunk.content or ""
        if max_context_chars and len(content) > max_context_chars:
            content = content[:max_context_chars] + "..."
        if content:
            contexts.append(content)
    return contexts


def _mean(values: Iterable[float]) -> Optional[float]:
    vals = []
    for v in values:
        if v is None:
            continue
        try:
            fv = float(v)
        except Exception:
            continue
        if math.isnan(fv):
            continue
        vals.append(fv)
    if not vals:
        return None
    return sum(vals) / len(vals)


def _resolve_metrics(metric_names: List[str]):
    """
    Map user-friendly names to RAGAS metric objects.
    Returns: list[Metric]
    """
    try:
        from ragas.metrics import Faithfulness, ResponseRelevancy, LLMContextPrecisionWithoutReference
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "RAGAS is not installed. Please run: pip install -r backend/requirements.txt"
        ) from exc

    resolved = []
    for name in metric_names or []:
        key = (name or "").strip().lower()
        if key in {"faithfulness"}:
            resolved.append(Faithfulness())
            continue
        if key in {"response_relevancy", "answer_relevancy"}:
            resolved.append(ResponseRelevancy())
            continue
        if key in {"context_precision", "llm_context_precision_without_reference"}:
            resolved.append(LLMContextPrecisionWithoutReference())
            continue
        raise ValueError(f"Unsupported RAGAS metric: {name}")
    if not resolved:
        resolved = [Faithfulness(), ResponseRelevancy()]
    return resolved


def _build_llm_and_embeddings():
    """
    Build LangChain LLM + embeddings compatible with RAGAS wrappers.
    """
    try:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "langchain_openai is required for RAGAS evaluation. Please reinstall backend requirements."
        ) from exc

    http_client, http_async_client = _build_http_clients()

    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE,
        temperature=0.0,
        streaming=False,
        timeout=settings.LLM_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
        http_client=http_client,
        http_async_client=http_async_client,
    )

    provider = (settings.EMBEDDING_PROVIDER or "openai_compatible").lower()
    if provider == "local":
        from langchain_community.embeddings import HuggingFaceEmbeddings

        embeddings = HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL)
    else:
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE
        embeddings = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            api_key=api_key,
            base_url=base_url,
        )

    return llm, embeddings


def run_conversation_ragas_evaluation(
    *,
    run_id: UUID,
    tenant_id: UUID,
    account_id: str,
    conversation_id: UUID,
    metric_names: List[str],
    max_turns: int,
    skip_empty_contexts: bool,
) -> None:
    """
    Background task entry: run RAGAS evaluation and persist results.
    """
    db = SessionLocal()
    try:
        run = (
            db.query(RagasEvaluationRun)
            .filter(
                RagasEvaluationRun.id == run_id,
                RagasEvaluationRun.tenant_id == tenant_id,
            )
            .first()
        )
        if not run:
            return

        run.status = "running"
        run.started_at = datetime.utcnow()
        run.error_message = None
        db.commit()

        # tenant membership check
        DatasetService.ensure_member(db, tenant_id, account_id)

        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
            .first()
        )
        if not conversation:
            run.status = "failed"
            run.error_message = "Conversation not found"
            run.finished_at = datetime.utcnow()
            db.commit()
            return

        # enforce doc access and keep only allowed docs
        allowed_doc_ids = filter_allowed_document_ids(
            db, tenant_id, account_id, conversation.document_ids or []
        )

        messages = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation_id,
                Message.tenant_id == tenant_id,
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        turns = _pair_turns(messages)
        if max_turns and max_turns > 0:
            turns = turns[-max_turns:]

        # Build evaluation items + ragas samples
        eval_items: List[Dict[str, Any]] = []
        for idx, (user_msg, assistant_msg) in enumerate(turns, 1):
            contexts = _extract_contexts(
                db=db,
                tenant_id=tenant_id,
                allowed_document_ids=allowed_doc_ids,
                citations=assistant_msg.citations or [],
            )
            if skip_empty_contexts and not contexts:
                continue
            eval_items.append(
                {
                    "turn_index": idx,
                    "user_message_id": user_msg.id,
                    "assistant_message_id": assistant_msg.id,
                    "user_input": user_msg.content,
                    "response": assistant_msg.content,
                    "retrieved_contexts": contexts,
                    "citations": assistant_msg.citations or [],
                }
            )

        if not eval_items:
            run.status = "failed"
            run.error_message = "No evaluatable turns (missing contexts/citations)"
            run.finished_at = datetime.utcnow()
            db.commit()
            return

        # Import ragas lazily
        try:
            from ragas import EvaluationDataset, SingleTurnSample, evaluate
            from ragas.embeddings import LangchainEmbeddingsWrapper
            from ragas.llms import LangchainLLMWrapper
        except Exception as exc:  # pragma: no cover
            run.status = "failed"
            run.error_message = f"RAGAS import failed: {exc}"
            run.finished_at = datetime.utcnow()
            db.commit()
            return

        llm, embeddings = _build_llm_and_embeddings()
        ragas_llm = LangchainLLMWrapper(llm)
        ragas_embeddings = LangchainEmbeddingsWrapper(embeddings)

        metrics = _resolve_metrics(metric_names)
        metric_keys = [getattr(m, "name", None) or str(m) for m in metrics]

        samples = [
            SingleTurnSample(
                user_input=item["user_input"],
                response=item["response"],
                retrieved_contexts=item["retrieved_contexts"],
            )
            for item in eval_items
        ]
        dataset = EvaluationDataset(samples=samples)

        result = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=ragas_llm,
            embeddings=ragas_embeddings,
            show_progress=False,
            raise_exceptions=False,
            allow_nest_asyncio=False,
        )

        # Persist items
        db.query(RagasEvaluationItem).filter(
            RagasEvaluationItem.run_id == run_id,
            RagasEvaluationItem.tenant_id == tenant_id,
        ).delete(synchronize_session=False)

        for idx, item in enumerate(eval_items):
            scores = {}
            if idx < len(result.scores):
                scores = result.scores[idx] or {}
            db.add(
                RagasEvaluationItem(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    turn_index=item["turn_index"],
                    user_message_id=item["user_message_id"],
                    assistant_message_id=item["assistant_message_id"],
                    user_input=item["user_input"],
                    response=item["response"],
                    retrieved_contexts=item["retrieved_contexts"],
                    citations=item["citations"],
                    scores=scores,
                )
            )

        summary: Dict[str, Any] = {"items": len(eval_items)}
        for key in metric_keys:
            summary[key] = _mean(row.get(key) for row in result.scores)
        summary["total_tokens"] = getattr(result, "total_tokens", None)
        summary["total_cost"] = getattr(result, "total_cost", None)

        run.status = "completed"
        run.metrics = metric_keys
        run.params = {
            "requested_metrics": metric_names,
            "max_turns": max_turns,
            "skip_empty_contexts": skip_empty_contexts,
        }
        run.summary = summary
        run.finished_at = datetime.utcnow()
        db.commit()

    except Exception as exc:
        try:
            run = (
                db.query(RagasEvaluationRun)
                .filter(
                    RagasEvaluationRun.id == run_id,
                    RagasEvaluationRun.tenant_id == tenant_id,
                )
                .first()
            )
            if run:
                run.status = "failed"
                run.error_message = str(exc)
                run.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()

