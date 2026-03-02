"""
RAGAS evaluation service.

- Supports conversation-based evaluation using stored chat messages + citations.
- Runs in FastAPI BackgroundTasks (sync function).
"""


import math
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

import httpx
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.core.utils import get_proxy_url
from app.models.chat import Conversation, Message
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.models.evaluation import (
    RagasEvaluationItem,
    RagasEvaluationRun,
    RagasRegressionCase,
    RagasRegressionItem,
    RagasRegressionRun,
)
from app.rag.embedding import create_langchain_embeddings_from_config
from app.rag.evaluation.regression_sample_builder import build_regression_item_meta, build_regression_sample
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids, get_allowed_document_id_sets


def _build_http_clients() -> tuple[httpx.Client, httpx.AsyncClient]:
    """
    Reuse the same proxy-handling logic as the RAG engine:
    - If a SOCKS proxy is detected, disable trust_env to avoid httpx issues.
    """
    proxy_url = get_proxy_url()
    trust_env = True
    if proxy_url and proxy_url.lower().startswith("socks"):
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
    account_id: str,
    citations: Any,
    allowed_document_ids: List[UUID] | None = None,
    dataset_id: UUID | None = None,
    max_context_chars: int = 4000,
) -> List[str]:
    """
    Resolve full chunk contents from stored citations.
    """
    if not citations:
        return []

    # Preserve citation ordering for context extraction and allow fallbacks for
    # non-chunk-backed citations (e.g. TAG/table injected docs).
    citation_items: list[dict[str, Any]] = []

    chunk_ids: List[UUID] = []
    seen_chunk_ids: set[UUID] = set()
    for item in citations:
        if item is None:
            continue
        if hasattr(item, "model_dump"):
            try:
                item = item.model_dump(mode="json")
            except Exception:
                continue
        if not isinstance(item, dict):
            continue

        raw_chunk = item.get("chunk_id")
        raw_doc = item.get("document_id")
        fallback_text = str(item.get("chunk_content") or item.get("quote") or item.get("text") or "").strip()

        chunk_id: UUID | None
        try:
            chunk_id = UUID(str(raw_chunk)) if raw_chunk else None
        except Exception:
            chunk_id = None

        doc_id: UUID | None
        try:
            doc_id = UUID(str(raw_doc)) if raw_doc else None
        except Exception:
            doc_id = None

        citation_items.append({"chunk_id": chunk_id, "document_id": doc_id, "fallback": fallback_text})
        if chunk_id and chunk_id not in seen_chunk_ids:
            seen_chunk_ids.add(chunk_id)
            chunk_ids.append(chunk_id)

    if not citation_items:
        return []

    chunks: list[DocumentChunk] = []
    if chunk_ids:
        chunks = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.id.in_(chunk_ids),
            )
            .all()
        )
    chunk_map: Dict[UUID, DocumentChunk] = {c.id: c for c in (chunks or [])}

    # Defense-in-depth: only materialize contexts for documents the account can read.
    allowed_set: set[UUID] | None = None
    if allowed_document_ids:
        allowed_set = set(allowed_document_ids)
    else:
        candidate_doc_ids = {c.document_id for c in chunks if getattr(c, "document_id", None)}
        candidate_doc_ids |= {d for d in (it.get("document_id") for it in citation_items) if d is not None}
        if candidate_doc_ids:
            allowed_ids, _missing = get_allowed_document_id_sets(
                db,
                tenant_id,
                account_id,
                list(candidate_doc_ids),
                check_member=True,
            )
            allowed_set = set(allowed_ids)
        else:
            allowed_set = set()

    if dataset_id is not None and allowed_set:
        # Enforce dataset scope when evaluation is dataset-scoped.
        ds_rows = (
            db.query(DBDocument.id, DBDocument.dataset_id)
            .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(allowed_set)))
            .all()
        )
        allowed_set = {doc_id for doc_id, ds_id in ds_rows if ds_id is not None and str(ds_id) == str(dataset_id)}

    contexts: List[str] = []
    seen_context_keys: set[str] = set()
    for it in citation_items:
        cid: UUID | None = it.get("chunk_id")
        chunk = chunk_map.get(cid) if cid else None

        # Prefer document_id from the resolved chunk; fall back to citation metadata.
        doc_id = getattr(chunk, "document_id", None) if chunk is not None else it.get("document_id")
        if allowed_set is not None:
            # Fail closed if we can't associate the context with a document under ACL trimming.
            if doc_id is None or doc_id not in allowed_set:
                continue

        content = (getattr(chunk, "content", None) if chunk is not None else None) or it.get("fallback") or ""
        content = str(content or "")
        if not content.strip():
            continue

        if max_context_chars and len(content) > max_context_chars:
            content = content[:max_context_chars] + "..."

        # Keep deterministic ordering while avoiding duplicates.
        key = str(cid) if cid else f"text:{content[:64]}"
        if key in seen_context_keys:
            continue
        seen_context_keys.add(key)
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


def _build_regression_gate_summary(eval_items: list[dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute non-LLM regression gate metrics from per-item meta.

    These are derived from the regression case's human-verified evidence pointers
    and the system's retrieved citations (chunk_id overlap), so they stay cheap and
    deterministic (usable even when RAGAS metrics are missing/partial).
    """

    metas: list[dict[str, Any]] = []
    for item in eval_items or []:
        if not isinstance(item, dict):
            continue
        meta = item.get("item_meta")
        metas.append(meta if isinstance(meta, dict) else {})

    out = _build_retrieval_metrics_summary(metas)

    # Answer-level deterministic gate signals (best-effort, offline):
    # - faithfulness_det: claim support ratio vs retrieved_contexts
    # - refusal_correctness: compares expected_refusal vs abstain_triggered (only on labeled cases)
    def _mean_float(key: str) -> Optional[float]:
        vals: list[float] = []
        for m in metas:
            v = m.get(key)
            if v is None:
                continue
            try:
                fv = float(v)
            except Exception:
                continue
            if math.isnan(fv):
                continue
            vals.append(fv)
        return _mean(vals)

    faith_det = _mean_float("faithfulness_det")
    if faith_det is not None:
        out["faithfulness_det"] = faith_det
        # Back-compat / convenience: expose under "faithfulness" when RAGAS is not used.
        # `_merge_summary_with_regression_gate` is intentionally "do not override existing keys",
        # so RAGAS faithfulness wins when present.
        out["faithfulness"] = faith_det

    labeled = 0
    correct = 0
    false_pos = 0
    false_neg = 0
    for m in metas:
        exp = m.get("expected_refusal")
        if exp is None:
            continue
        abst = m.get("abstain_triggered")
        if abst is None:
            continue
        labeled += 1
        exp_b = bool(exp)
        abst_b = bool(abst)
        if exp_b == abst_b:
            correct += 1
        else:
            if (not exp_b) and abst_b:
                false_pos += 1
            if exp_b and (not abst_b):
                false_neg += 1

    if labeled > 0:
        out["refusal_correctness"] = round(float(correct) / float(labeled), 4)
        out["refusal_false_positive_rate"] = round(float(false_pos) / float(labeled), 4)
        out["refusal_false_negative_rate"] = round(float(false_neg) / float(labeled), 4)
        out["refusal_labeled_items"] = int(labeled)

    return out


def _build_retrieval_metrics_summary(metas: list[dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute retrieval-only metrics from a list of item_meta dicts.

    These stay cheap/deterministic (usable when RAGAS metrics are missing/partial).
    """

    def _mean_bool(key: str) -> Optional[float]:
        vals: list[float] = []
        for m in metas:
            v = m.get(key)
            if v is None:
                continue
            vals.append(1.0 if bool(v) else 0.0)
        return _mean(vals)

    return {
        "retrieval_recall": _mean(m.get("retrieval_recall") for m in metas),
        "retrieval_mrr": _mean(m.get("retrieval_mrr") for m in metas),
        "retrieval_ndcg_at_10": _mean(m.get("retrieval_ndcg_at_10") for m in metas),
        "retrieval_ndcg_at_20": _mean(m.get("retrieval_ndcg_at_20") for m in metas),
        "retrieval_hit_at_1": _mean_bool("retrieval_hit_at_1"),
        "retrieval_hit_at_3": _mean_bool("retrieval_hit_at_3"),
        "retrieval_hit_at_5": _mean_bool("retrieval_hit_at_5"),
        "retrieval_hit_at_10": _mean_bool("retrieval_hit_at_10"),
        "retrieval_hit_at_20": _mean_bool("retrieval_hit_at_20"),
        "abstain_rate": _mean_bool("abstain_triggered"),
    }


def _build_regression_slice_summaries(
    eval_items: list[dict[str, Any]],
    *,
    max_buckets: int = 20,
) -> dict[str, Any]:
    """
    Slice retrieval-only metrics by stable buckets (file_type/language/directory).

    Returns a JSON-safe dict meant for report exports (bounded).
    """
    max_buckets = max(0, min(int(max_buckets or 0), 200))

    metas: list[dict[str, Any]] = []
    for item in eval_items or []:
        if not isinstance(item, dict):
            continue
        meta = item.get("item_meta")
        metas.append(meta if isinstance(meta, dict) else {})

    def _bucketize(*, key: str) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for m in metas:
            raw = m.get(key)
            b = str(raw or "").strip().lower() or "unknown"
            if len(b) > 80:
                b = b[:80]
            groups.setdefault(b, []).append(m)

        rows: list[dict[str, Any]] = []
        for bucket, items in groups.items():
            summary = _build_retrieval_metrics_summary(items)
            rows.append({"key": bucket, "items": int(len(items)), **summary})

        rows.sort(key=lambda o: (-int(o.get("items") or 0), str(o.get("key") or "")))
        truncated = False
        if max_buckets > 0 and len(rows) > max_buckets:
            rows = rows[:max_buckets]
            truncated = True
        return {"buckets": rows, "truncated": bool(truncated)}

    return {
        "file_type": _bucketize(key="slice_file_type"),
        "language": _bucketize(key="slice_language"),
        "directory": _bucketize(key="slice_directory"),
        "access_mode": _bucketize(key="slice_access_mode"),
        "hit_type": _bucketize(key="slice_hit_type"),
        "quality": _bucketize(key="slice_quality_bucket"),
        "pipeline_hash": _bucketize(key="slice_pipeline_hash"),
    }


def _merge_summary_with_regression_gate(
    summary: Dict[str, Any],
    *,
    eval_items: list[dict[str, Any]],
) -> Dict[str, Any]:
    out = dict(summary or {})
    gate = _build_regression_gate_summary(eval_items)
    # Do not override existing summary keys (e.g. RAGAS metrics like "faithfulness").
    for k, v in (gate or {}).items():
        if k in out and out.get(k) is not None:
            continue
        out[k] = v
    out["retrieval_slices"] = _build_regression_slice_summaries(eval_items)
    return out


def _parse_uuid_list(raw_list: Any) -> List[UUID]:
    out: List[UUID] = []
    if not raw_list:
        return out
    for item in raw_list:
        if not item:
            continue
        try:
            out.append(UUID(str(item)))
        except Exception:
            continue
    return out


def _json_safe(value: Any) -> Any:
    """Convert UUID and other types to JSON-serializable structure for JSONB storage."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _resolve_case_scope(
    *,
    db,
    tenant_id: UUID,
    account_id: str,
    case: RagasRegressionCase,
) -> tuple[List[UUID] | None, UUID | None]:
    """
    Resolve retrieval scope for regression case:
    1) case.document_ids (priority)
    2) case.dataset_id -> dataset-scoped retrieval (no document_id enumeration)
    3) fallback: open-scope retrieval (tenant + ACL trimming)
    """
    raw_doc_ids = _parse_uuid_list(case.document_ids or [])
    if raw_doc_ids:
        return filter_allowed_document_ids(db, tenant_id, account_id, raw_doc_ids), None

    if case.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, case.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)
        return None, case.dataset_id

    return None, None


def _resolve_metrics(metric_names: List[str]):
    """
    Map user-friendly names to RAGAS metric objects.
    Returns: list[Metric]
    """
    try:
        from ragas.metrics import (
            AnswerCorrectness,
            AnswerSimilarity,
            ContextPrecision,
            ContextRecall,
            Faithfulness,
            IDBasedContextPrecision,
            IDBasedContextRecall,
            LLMContextPrecisionWithoutReference,
            ResponseRelevancy,
        )
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "RAGAS is not installed. Please run: pip install ragas"
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
        if key in {"answer_similarity"}:
            resolved.append(AnswerSimilarity())
            continue
        if key in {"answer_correctness"}:
            resolved.append(AnswerCorrectness())
            continue
        if key in {"context_recall"}:
            resolved.append(ContextRecall())
            continue
        if key in {"context_precision"}:
            resolved.append(ContextPrecision())
            continue
        if key in {"id_based_context_recall"}:
            resolved.append(IDBasedContextRecall())
            continue
        if key in {"id_based_context_precision"}:
            resolved.append(IDBasedContextPrecision())
            continue
        if key in {"llm_context_precision_without_reference"}:
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

    http_client, http_async_client = _build_http_clients()
    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=normalize_openai_compatible_base_url(settings.LLM_API_BASE),
        temperature=0.0,
        streaming=False,
        timeout=settings.LLM_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
        http_client=http_client,
        http_async_client=http_async_client,
    )

    provider = (settings.EMBEDDING_PROVIDER or "openai_compatible").lower()
    if provider == "local":

        embeddings = HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL)
    elif provider == "dashscope":
        embeddings = create_langchain_embeddings_from_config(
            provider="dashscope",
            model=settings.EMBEDDING_MODEL,
            api_key=settings.EMBEDDING_API_KEY or settings.LLM_API_KEY or "",
            base_url=settings.EMBEDDING_API_BASE or settings.LLM_API_BASE or "",
            dimension=None,
        )
    else:
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        base_url = normalize_openai_compatible_base_url(settings.EMBEDDING_API_BASE or settings.LLM_API_BASE)
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
                account_id=account_id,
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
        except ImportError as exc:  # pragma: no cover
            run.status = "failed"
            run.error_message = f"RAGAS is not installed: {exc} (hint: pip install ragas)"
            run.finished_at = datetime.utcnow()
            db.commit()
            return
        except Exception as exc:  # pragma: no cover
            run.status = "failed"
            run.error_message = f"RAGAS import failed: {type(exc).__name__}: {exc}"
            run.finished_at = datetime.utcnow()
            db.commit()
            raise

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
        summary.update(_build_regression_gate_summary(eval_items))

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


def run_regression_ragas_evaluation(
    *,
    run_id: UUID,
    tenant_id: UUID,
    account_id: str,
    case_ids: List[UUID],
    dataset_id: UUID | None,
    metric_names: List[str],
    skip_empty_contexts: bool,
    max_cases: int,
    rag_params: Dict[str, Any],
) -> None:
    """
    Background task entry: run RAGAS regression evaluation (case-based) and persist results.
    """
    db = SessionLocal()
    try:
        run = (
            db.query(RagasRegressionRun)
            .filter(RagasRegressionRun.id == run_id, RagasRegressionRun.tenant_id == tenant_id)
            .first()
        )
        if not run:
            return

        run.status = "running"
        run.started_at = datetime.utcnow()
        db.commit()

        DatasetService.ensure_member(db, tenant_id, account_id)

        q = db.query(RagasRegressionCase).filter(RagasRegressionCase.tenant_id == tenant_id)
        if dataset_id:
            q = q.filter(RagasRegressionCase.dataset_id == dataset_id)
        if case_ids:
            q = q.filter(RagasRegressionCase.id.in_(case_ids))
        cases = q.order_by(RagasRegressionCase.updated_at.desc()).limit(max_cases).all()
        if not cases:
            run.status = "failed"
            run.error_message = "No regression cases found"
            run.finished_at = datetime.utcnow()
            db.commit()
            return

        # Best-effort slice attributes for report slicing (derived from evidence documents).
        #
        # We map each case -> bucket keys using its reference_sources[].document_id.
        # These are used for "retrieval-only" slicing metrics, and are safe to compute
        # even when RAGAS metrics are disabled/unavailable.
        #
        # Keep in sync with dataset profiling and evidence drift audits (stable + actionable).
        from app.core.pipeline_versions import get_active_pipeline_hash  # noqa: WPS433
        from app.services.dataset_profile_service import (  # noqa: WPS433
            directory_bucket_from_source_path,
            extract_language_bucket,
            quality_bucket_from_governance_quality,
        )

        def _normalize_access_mode(value: object) -> str:
            s = str(value or "").strip().lower()
            if not s or s == "inherit":
                return "inherit"
            if s in {"only_me", "partial_members", "all_team_members"}:
                return s
            return "unknown"

        def _normalize_pipeline_hash(value: object) -> str:
            s = str(value or "").strip()
            if not s:
                return "unknown"
            # Bound for UI/report readability while keeping enough entropy.
            return s[:16]

        evidence_doc_ids: set[UUID] = set()
        case_to_evidence_docs: dict[UUID, list[UUID]] = {}
        for case in cases:
            doc_ids: list[UUID] = []
            seen: set[UUID] = set()
            for src in getattr(case, "reference_sources", None) or []:
                raw = None
                if isinstance(src, dict):
                    raw = src.get("document_id")
                else:
                    raw = getattr(src, "document_id", None)
                if not raw:
                    continue
                try:
                    did = UUID(str(raw))
                except Exception:
                    continue
                if did in seen:
                    continue
                seen.add(did)
                doc_ids.append(did)
                evidence_doc_ids.add(did)
            if doc_ids:
                case_to_evidence_docs[case.id] = doc_ids

        doc_attr: dict[UUID, dict[str, str]] = {}
        if evidence_doc_ids:
            rows = (
                db.query(DBDocument.id, DBDocument.file_type, DBDocument.access_mode, DBDocument.doc_metadata)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(evidence_doc_ids)))
                .all()
            )
            for doc_id, file_type, access_mode, meta in rows:
                meta_dict = meta if isinstance(meta, dict) else {}
                lang = extract_language_bucket(meta_dict)
                dir_bucket = directory_bucket_from_source_path(meta_dict.get("source_path"))
                ft = str(file_type or "").strip().lower() or "unknown"
                active_ph = get_active_pipeline_hash(meta_dict)
                ph = _normalize_pipeline_hash(active_ph)
                quality_bucket = quality_bucket_from_governance_quality(meta_dict.get("governance_quality"))
                acc = _normalize_access_mode(access_mode)
                doc_attr[doc_id] = {
                    "file_type": ft,
                    "language": lang,
                    "directory": dir_bucket,
                    "pipeline_hash": ph,
                    "quality_bucket": quality_bucket,
                    "access_mode": acc,
                }

        case_slice_meta: dict[UUID, dict[str, str]] = {}
        for case in cases:
            docs = case_to_evidence_docs.get(case.id) or []
            fts = {doc_attr.get(d, {}).get("file_type", "unknown") for d in docs}
            langs = {doc_attr.get(d, {}).get("language", "unknown") for d in docs}
            dirs = {doc_attr.get(d, {}).get("directory", "root") for d in docs}
            phs = {doc_attr.get(d, {}).get("pipeline_hash", "unknown") for d in docs}
            quals = {doc_attr.get(d, {}).get("quality_bucket", "unknown") for d in docs}
            accs = {doc_attr.get(d, {}).get("access_mode", "inherit") for d in docs}

            def _stable_bucket(values: set[str], *, default: str) -> str:
                cleaned = {str(v or "").strip().lower() for v in values if str(v or "").strip()}
                if not cleaned:
                    return default
                if len(cleaned) == 1:
                    return next(iter(cleaned))
                return "mixed"

            case_slice_meta[case.id] = {
                "slice_file_type": _stable_bucket(fts, default="unknown"),
                "slice_language": _stable_bucket(langs, default="unknown"),
                "slice_directory": _stable_bucket(dirs, default="root"),
                "slice_access_mode": _stable_bucket(accs, default="inherit"),
                "slice_pipeline_hash": _stable_bucket(phs, default="unknown"),
                "slice_quality_bucket": _stable_bucket(quals, default="unknown"),
            }

        eval_items: List[Dict[str, Any]] = []
        normalized_metric_names = [str(m or "").strip().lower() for m in (metric_names or []) if str(m or "").strip()]
        retrieval_only = not bool(normalized_metric_names)
        # Deterministic (no-RAGAS) answer-level gate mode:
        # - still runs the RAG graph to produce an answer/citations
        # - computes offline metrics (faithfulness_det/refusal_correctness) via item_meta aggregation
        det_metrics = {"faithfulness_det", "refusal_correctness"}
        deterministic_only = (not retrieval_only) and all(m in det_metrics for m in normalized_metric_names)
        for case in cases:
            scope_doc_ids, scope_dataset_id = _resolve_case_scope(
                db=db, tenant_id=tenant_id, account_id=account_id, case=case
            )
            response: str = ""
            citations: Any = []
            graph_result: dict[str, Any] = {}

            # === Multi-modal evaluation harness (Wave19-T066) ===
            #
            # Regression runs can include image/table-heavy questions. The main chat endpoint performs
            # deterministic modality routing + context injection before running the RAG graph. We do
            # the same here so regression runs reflect production behavior.
            multimodal_router_meta: dict[str, Any] = {"enabled": True, "modality": "text", "reasons": []}
            tag_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}
            image_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}
            injected_docs: list[Any] = []

            # Optional: allow regression cases to force a modality to keep runs deterministic.
            extra_d = case.extra if isinstance(getattr(case, "extra", None), dict) else {}
            override_raw = str(extra_d.get("modality") or extra_d.get("query_modality") or "").strip().lower()

            modality: str
            if override_raw in {"text", "table", "image"}:
                modality = override_raw
                multimodal_router_meta["modality"] = modality
                multimodal_router_meta["reasons"] = ["override"]
            else:
                try:
                    from app.rag.policy.modality_router import classify_query_modality

                    modality, reasons = classify_query_modality(case.question)
                    modality = str(modality or "text").strip().lower() or "text"
                    multimodal_router_meta["modality"] = modality
                    multimodal_router_meta["reasons"] = reasons
                except Exception as exc:  # noqa: BLE001
                    modality = "text"
                    multimodal_router_meta["enabled"] = False
                    multimodal_router_meta["modality"] = "text"
                    multimodal_router_meta["reasons"] = [f"router_exception:{str(exc)[:80]}"]

            # Table/TAG injection: requires document_ids. For dataset-scoped cases, we resolve a bounded
            # list of recent docs in the dataset and ACL-trim them.
            try:
                if modality == "table":
                    from app.services.chat_tag_service import build_chat_tag_context_docs

                    doc_ids_for_tag = list(scope_doc_ids or [])
                    if not doc_ids_for_tag and scope_dataset_id is not None:
                        from app.models.document import Document as DBDocument
                        from app.services.document_access import filter_allowed_document_ids

                        max_doc_ids = int(getattr(settings, "CHAT_TAG_MAX_DOC_IDS", 1000) or 1000)
                        cand_rows = (
                            db.query(DBDocument.id)
                            .filter(
                                DBDocument.tenant_id == tenant_id,
                                DBDocument.dataset_id == scope_dataset_id,
                                DBDocument.status == "completed",
                            )
                            .order_by(DBDocument.updated_at.desc())
                            .limit(max_doc_ids)
                            .all()
                        )
                        cand_ids = [row[0] for row in cand_rows if row and row[0]]
                        try:
                            doc_ids_for_tag = filter_allowed_document_ids(db, tenant_id, account_id, cand_ids)
                        except Exception:
                            doc_ids_for_tag = []

                    if doc_ids_for_tag:
                        tag_docs, tag_meta = build_chat_tag_context_docs(
                            db,
                            tenant_id=tenant_id,
                            document_ids=doc_ids_for_tag,
                            question=case.question,
                        )
                        if tag_docs:
                            injected_docs.extend(tag_docs)
                    else:
                        tag_meta = {"enabled": False, "used": False, "reason": "missing_document_scope"}
            except Exception as exc:  # noqa: BLE001
                tag_meta = {"enabled": False, "used": False, "reason": f"tag_exception:{str(exc)[:120]}"}

            # Image injection: CLIP index is dataset-scoped; best-effort infer dataset_id for doc-scoped cases.
            try:
                if modality == "image":
                    from app.models.document import Document as DBDocument
                    from app.services.chat_image_service import build_chat_image_context_docs

                    ds_for_images = scope_dataset_id
                    if ds_for_images is None and scope_doc_ids:
                        rows = (
                            db.query(DBDocument.dataset_id)
                            .filter(
                                DBDocument.tenant_id == tenant_id,
                                DBDocument.id.in_(list(scope_doc_ids)),
                            )
                            .distinct()
                            .all()
                        )
                        ds_ids = {row[0] for row in rows if row and row[0]}
                        if len(ds_ids) == 1:
                            ds_for_images = next(iter(ds_ids))

                    if ds_for_images is not None:
                        image_docs, image_meta = build_chat_image_context_docs(
                            db,
                            tenant_id=tenant_id,
                            account_id=account_id,
                            dataset_id=ds_for_images,
                            question=case.question,
                        )
                        if image_docs:
                            injected_docs.extend(image_docs)
                    else:
                        image_meta = {"enabled": False, "used": False, "reason": "missing_dataset_id"}
            except Exception as exc:  # noqa: BLE001
                image_meta = {"enabled": False, "used": False, "reason": f"image_exception:{str(exc)[:120]}"}

            from app.rag.pipelines.langgraph import build_rag_graph, build_rag_state, run_rag_workflow_functional

            state = build_rag_state(
                question=case.question,
                history=[],
                document_ids=(scope_doc_ids or None),
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=scope_dataset_id,
                top_k=int(rag_params.get("top_k", 5)),
                score_threshold=float(rag_params.get("score_threshold", 0.7)),
                retrieval_mode=str(rag_params.get("retrieval_mode", "hybrid")),
                alpha=float(rag_params.get("alpha", 0.6)),
                fusion_strategy=rag_params.get("fusion_strategy"),
                fusion_budgets=rag_params.get("fusion_budgets"),
                fusion_min_scores=rag_params.get("fusion_min_scores"),
                fusion_weights=rag_params.get("fusion_weights"),
                enable_weight_rerank=bool(rag_params.get("enable_weight_rerank", True)),
                vector_weight=float(rag_params.get("vector_weight", 0.6)),
                keyword_weight=float(rag_params.get("keyword_weight", 0.4)),
                mmr_lambda=float(rag_params.get("mmr_lambda", settings.RETRIEVAL_MMR_LAMBDA)),
                enable_reranker=bool(rag_params.get("enable_reranker", settings.ENABLE_RERANKER)),
                reranker_provider=rag_params.get("reranker_provider") or settings.RERANKER_PROVIDER,
                reranker_top_n=int(rag_params.get("reranker_top_n", settings.RERANKER_TOP_N)),
                structured_output=False,
                structured_preset=None,
                prompt_template_id=rag_params.get("prompt_template_id"),
                prompt_template_key=rag_params.get("prompt_template_key"),
                prompt_ab_experiment_key=rag_params.get("prompt_ab_experiment_key"),
                ab_user_key=account_id,
                db=db,
            )

            if injected_docs:
                # Legacy surface: retrieval node consumes tag_docs (prepended before text retrieval results).
                state["tag_docs"] = injected_docs
            state["tag_meta"] = tag_meta
            state["image_meta"] = image_meta
            state["multimodal_router"] = multimodal_router_meta

            if retrieval_only:
                from app.rag.pipelines.langgraph import _retrieve_node

                graph_result = _retrieve_node(state) or {}
                citations = graph_result.get("citations") or []
                response = ""
            else:
                thread_id = f"regression:{run_id}:{case.id}"
                use_functional_api = bool(getattr(settings, "LANGGRAPH_USE_FUNCTIONAL_API", True))
                if use_functional_api:
                    graph_result = run_rag_workflow_functional(state, thread_id=thread_id, context=None) or {}
                else:
                    app = build_rag_graph()
                    recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
                    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
                    graph_result = app.invoke(state, config=config, context=None) or {}

                response = (graph_result or {}).get("answer") or ""
                citations = (graph_result or {}).get("citations") or []
            contexts = _extract_contexts(
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                allowed_document_ids=scope_doc_ids,
                dataset_id=scope_dataset_id,
                citations=citations,
            )
            if skip_empty_contexts and not contexts:
                continue
            meta = (graph_result or {}).get("metrics") or {}
            eval_item: Dict[str, Any] = {
                "case_id": case.id,
                "question": case.question,
                "response": response,
                "retrieved_contexts": contexts,
                "citations": citations,
                "abstain_triggered": bool((graph_result or {}).get("abstain_triggered")),
                "abstain_reason": (graph_result or {}).get("abstain_reason"),
                "top_relevance_score": meta.get("top_relevance_score") if isinstance(meta, dict) else None,
            }
            sample_kwargs, item_meta = build_regression_sample(case, eval_item)
            eval_item["sample_kwargs"] = sample_kwargs
            # Attach slice keys for report slicing (best-effort).
            merged_meta = dict(item_meta or {})
            merged_meta.update(case_slice_meta.get(case.id) or {})
            # Multi-modal slicing/debug (best-effort; safe-by-default).
            merged_meta.setdefault("slice_modality", str(multimodal_router_meta.get("modality") or "text"))
            merged_meta.setdefault("multimodal_router", dict(multimodal_router_meta))
            merged_meta.setdefault("tag_meta", dict(tag_meta))
            merged_meta.setdefault("image_meta", dict(image_meta))
            # Retrieval channel slice (best-effort): use top-1 hit_type from citations.
            hit_type = "unknown"
            try:
                c0 = (citations or [])[0] if isinstance(citations, list) else None
                if isinstance(c0, dict):
                    raw_ht = str(c0.get("hit_type") or "").strip().lower()
                    if raw_ht in {"vector", "keyword", "hybrid", "mmr", "tag", "image", "table"}:
                        hit_type = raw_ht
            except Exception:
                hit_type = "unknown"
            merged_meta.setdefault("slice_hit_type", hit_type)
            eval_item["item_meta"] = merged_meta
            eval_items.append(eval_item)

        if not eval_items:
            run.status = "failed"
            run.error_message = "No evaluatable cases (missing contexts/citations)"
            run.finished_at = datetime.utcnow()
            db.commit()
            return

        # Retrieval-only mode: skip RAGAS imports/evaluation and persist gate-ready results.
        if retrieval_only:
            db.query(RagasRegressionItem).filter(
                RagasRegressionItem.run_id == run_id,
                RagasRegressionItem.tenant_id == tenant_id,
            ).delete(synchronize_session=False)

            for item in eval_items:
                db.add(
                    RagasRegressionItem(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        case_id=item["case_id"],
                        question=item["question"],
                        response=item.get("response") or "",
                        retrieved_contexts=item["retrieved_contexts"],
                        citations=item["citations"],
                        scores={},
                        meta=build_regression_item_meta(
                            sample_kwargs=item.get("sample_kwargs"),
                            item_meta=item.get("item_meta"),
                        ),
                    )
                )

            summary: Dict[str, Any] = {"items": len(eval_items)}
            summary = _merge_summary_with_regression_gate(summary, eval_items=eval_items)

            run.status = "completed"
            run.metrics = []
            run.params = {
                **(run.params or {}),
                "requested_metrics": [],
                "skip_empty_contexts": skip_empty_contexts,
                "max_cases": max_cases,
                "rag_params": _json_safe(rag_params),
                "mode": "retrieval_only",
            }
            run.summary = summary
            run.finished_at = datetime.utcnow()
            db.commit()
            return

        # Deterministic answer-level gate mode: no RAGAS dependency, but does generate answers.
        if deterministic_only:
            db.query(RagasRegressionItem).filter(
                RagasRegressionItem.run_id == run_id,
                RagasRegressionItem.tenant_id == tenant_id,
            ).delete(synchronize_session=False)

            for item in eval_items:
                meta = item.get("item_meta") if isinstance(item.get("item_meta"), dict) else {}
                scores: dict[str, Any] = {}
                if "faithfulness_det" in normalized_metric_names:
                    if meta.get("faithfulness_det") is not None:
                        scores["faithfulness_det"] = meta.get("faithfulness_det")
                if "refusal_correctness" in normalized_metric_names:
                    rc = meta.get("refusal_correct")
                    if isinstance(rc, bool):
                        scores["refusal_correctness"] = 1.0 if rc else 0.0

                db.add(
                    RagasRegressionItem(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        case_id=item["case_id"],
                        question=item["question"],
                        response=item.get("response") or "",
                        retrieved_contexts=item["retrieved_contexts"],
                        citations=item["citations"],
                        scores=scores,
                        meta=build_regression_item_meta(
                            sample_kwargs=item.get("sample_kwargs"),
                            item_meta=item.get("item_meta"),
                        ),
                    )
                )

            summary = {"items": len(eval_items)}
            summary = _merge_summary_with_regression_gate(summary, eval_items=eval_items)

            run.status = "completed"
            run.metrics = list(normalized_metric_names)
            run.params = {
                **(run.params or {}),
                "requested_metrics": list(normalized_metric_names),
                "skip_empty_contexts": skip_empty_contexts,
                "max_cases": max_cases,
                "rag_params": _json_safe(rag_params),
                "mode": "deterministic_gate",
            }
            run.summary = summary
            run.finished_at = datetime.utcnow()
            db.commit()
            return

        try:
            from ragas import EvaluationDataset, SingleTurnSample, evaluate
            from ragas.embeddings import LangchainEmbeddingsWrapper
            from ragas.llms import LangchainLLMWrapper
        except ImportError as exc:  # pragma: no cover
            run.status = "failed"
            run.error_message = f"RAGAS is not installed: {exc} (hint: pip install ragas)"
            run.finished_at = datetime.utcnow()
            db.commit()
            return
        except Exception as exc:  # pragma: no cover
            run.status = "failed"
            run.error_message = f"RAGAS import failed: {type(exc).__name__}: {exc}"
            run.finished_at = datetime.utcnow()
            db.commit()
            raise

        llm, embeddings = _build_llm_and_embeddings()
        ragas_llm = LangchainLLMWrapper(llm)
        ragas_embeddings = LangchainEmbeddingsWrapper(embeddings)

        metrics = _resolve_metrics(metric_names)
        metric_keys = [getattr(m, "name", None) or str(m) for m in metrics]

        samples = [SingleTurnSample(**(item.get("sample_kwargs") or {})) for item in eval_items]
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

        db.query(RagasRegressionItem).filter(
            RagasRegressionItem.run_id == run_id,
            RagasRegressionItem.tenant_id == tenant_id,
        ).delete(synchronize_session=False)

        for idx, item in enumerate(eval_items):
            scores = {}
            if idx < len(result.scores):
                scores = result.scores[idx] or {}
            db.add(
                RagasRegressionItem(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    case_id=item["case_id"],
                    question=item["question"],
                    response=item["response"],
                    retrieved_contexts=item["retrieved_contexts"],
                    citations=item["citations"],
                    scores=scores,
                    meta=build_regression_item_meta(
                        sample_kwargs=item.get("sample_kwargs"),
                        item_meta=item.get("item_meta"),
                    ),
                )
            )

        summary: Dict[str, Any] = {"items": len(eval_items)}
        for key in metric_keys:
            summary[key] = _mean(row.get(key) for row in result.scores)
        summary["total_tokens"] = getattr(result, "total_tokens", None)
        summary["total_cost"] = getattr(result, "total_cost", None)
        summary = _merge_summary_with_regression_gate(summary, eval_items=eval_items)

        run.status = "completed"
        run.metrics = metric_keys
        run.params = {
            **(run.params or {}),
            "requested_metrics": metric_names,
            "skip_empty_contexts": skip_empty_contexts,
            "max_cases": max_cases,
            "rag_params": _json_safe(rag_params),
        }
        run.summary = summary
        run.finished_at = datetime.utcnow()
        db.commit()

    except Exception as exc:
        try:
            run = (
                db.query(RagasRegressionRun)
                .filter(RagasRegressionRun.id == run_id, RagasRegressionRun.tenant_id == tenant_id)
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
