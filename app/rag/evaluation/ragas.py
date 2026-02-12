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

    # Defense-in-depth: only materialize contexts for documents the account can read.
    allowed_set: set[UUID] | None = None
    if allowed_document_ids:
        allowed_set = set(allowed_document_ids)
    else:
        candidate_doc_ids = {c.document_id for c in chunks if getattr(c, "document_id", None)}
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
    for cid in chunk_ids:
        chunk = chunk_map.get(cid)
        if not chunk:
            continue
        if allowed_set is not None and chunk.document_id not in allowed_set:
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

    return _build_retrieval_metrics_summary(metas)


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
    out.update(_build_regression_gate_summary(eval_items))
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
        def _normalize_language_bucket(value: object) -> str:
            s = str(value or "").strip()
            if not s:
                return "unknown"
            lowered = s.lower()
            if lowered in {"mixed", "multilingual", "multi"}:
                return "mixed"
            if any(sep in lowered for sep in (",", ";", "|", "+", "/")):
                return "mixed"
            if lowered.startswith("zh"):
                return "zh"
            if lowered.startswith("en"):
                return "en"
            return "unknown"

        def _dir_bucket_from_source_path(value: object) -> str:
            raw = str(value or "").replace("\\", "/").strip()
            if not raw or raw in {".", "/"}:
                return "root"
            raw = raw.lstrip("/")
            head = raw.split("/", 1)[0].strip()
            return head or "root"

        def _normalize_pipeline_hash(value: object) -> str:
            s = str(value or "").strip()
            if not s:
                return "unknown"
            # Bound to a stable length for UI/report readability while keeping uniqueness.
            return s[:64]

        def _quality_bucket_from_governance_quality(value: object) -> str:
            q = value if isinstance(value, dict) else {}
            if not q:
                return "unknown"
            try:
                density = float(q.get("density")) if q.get("density") is not None else None
            except Exception:
                density = None
            try:
                heading_ratio = float(q.get("heading_ratio")) if q.get("heading_ratio") is not None else None
            except Exception:
                heading_ratio = None
            try:
                content_chars = int(q.get("content_chars")) if q.get("content_chars") is not None else None
            except Exception:
                content_chars = None

            # Stable, coarse buckets (avoid overfitting thresholds).
            if content_chars is not None and content_chars < 200:
                return "tiny"
            if heading_ratio is not None and heading_ratio >= 0.75:
                return "outline_heavy"
            if density is None:
                return "unknown"
            if density < 0.08:
                return "low_density"
            if density < 0.15:
                return "mid_density"
            return "high_density"

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
                db.query(DBDocument.id, DBDocument.file_type, DBDocument.doc_metadata)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(evidence_doc_ids)))
                .all()
            )
            for doc_id, file_type, meta in rows:
                meta_dict = meta if isinstance(meta, dict) else {}
                # language: prefer top-level; fallback to governance_enrichment.
                lang = "unknown"
                if isinstance(meta_dict.get("language"), str):
                    lang = _normalize_language_bucket(meta_dict.get("language"))
                else:
                    enr = meta_dict.get("governance_enrichment")
                    if isinstance(enr, dict) and isinstance(enr.get("language"), str):
                        lang = _normalize_language_bucket(enr.get("language"))

                source_path = meta_dict.get("source_path")
                dir_bucket = _dir_bucket_from_source_path(source_path)
                ft = str(file_type or "").strip().lower() or "unknown"
                active_ph = meta_dict.get("active_pipeline_hash") or meta_dict.get("pipeline_hash")
                ph = _normalize_pipeline_hash(active_ph)
                quality_bucket = _quality_bucket_from_governance_quality(meta_dict.get("governance_quality"))
                doc_attr[doc_id] = {
                    "file_type": ft,
                    "language": lang,
                    "directory": dir_bucket,
                    "pipeline_hash": ph,
                    "quality_bucket": quality_bucket,
                }

        case_slice_meta: dict[UUID, dict[str, str]] = {}
        for case in cases:
            docs = case_to_evidence_docs.get(case.id) or []
            fts = {doc_attr.get(d, {}).get("file_type", "unknown") for d in docs}
            langs = {doc_attr.get(d, {}).get("language", "unknown") for d in docs}
            dirs = {doc_attr.get(d, {}).get("directory", "root") for d in docs}
            phs = {doc_attr.get(d, {}).get("pipeline_hash", "unknown") for d in docs}
            quals = {doc_attr.get(d, {}).get("quality_bucket", "unknown") for d in docs}

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
                "slice_pipeline_hash": _stable_bucket(phs, default="unknown"),
                "slice_quality_bucket": _stable_bucket(quals, default="unknown"),
            }

        eval_items: List[Dict[str, Any]] = []
        retrieval_only = not bool(metric_names)
        for case in cases:
            scope_doc_ids, scope_dataset_id = _resolve_case_scope(
                db=db, tenant_id=tenant_id, account_id=account_id, case=case
            )
            response: str = ""
            citations: Any = []
            graph_result: dict[str, Any] = {}

            if retrieval_only:
                from app.rag.pipelines.langgraph import _retrieve_node, build_rag_state

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
                graph_result = _retrieve_node(state) or {}
                citations = graph_result.get("citations") or []
                response = ""
            else:
                from app.rag.graph import run_rag_graph

                graph_result = run_rag_graph(
                    question=case.question,
                    history=[],
                    document_ids=scope_doc_ids,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    dataset_id=scope_dataset_id,
                    top_k=int(rag_params.get("top_k", 5)),
                    score_threshold=float(rag_params.get("score_threshold", 0.7)),
                    retrieval_mode=str(rag_params.get("retrieval_mode", "hybrid")),
                    alpha=float(rag_params.get("alpha", 0.6)),
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
            # Retrieval channel slice (best-effort): use top-1 hit_type from citations.
            hit_type = "unknown"
            try:
                c0 = (citations or [])[0] if isinstance(citations, list) else None
                if isinstance(c0, dict):
                    raw_ht = str(c0.get("hit_type") or "").strip().lower()
                    if raw_ht in {"vector", "keyword", "hybrid", "mmr"}:
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
