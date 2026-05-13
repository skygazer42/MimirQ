from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string
from app.models.chat import Conversation, Message
from app.services.chat_cache_runtime import (
    annotate_chat_cache_metrics,
    prepare_chat_cache_lookup,
)
from app.services.chat_conversation_titles import apply_auto_conversation_title
from app.services.chat_memory_runtime import (
    _retrieve_long_term_messages,
    _retrieve_structured_memory_records,
)
from app.services.chat_response_cache import get_cached_chat_response
from app.services.chat_scope import resolve_chat_conversation_scope
from app.services.conversation_summary_service import get_conversation_summary
from app.services.dataset_defaults import (
    load_dataset_metadata,
    resolve_single_dataset_id_for_documents,
)
from app.services.prompt_defaults import merge_prompt_defaults_with_dataset
from app.services.rag_config_template_apply import apply_rag_config_patch
from app.services.rag_config_template_defaults import (
    merge_rag_config_template_defaults_with_dataset,
)
from app.services.rag_config_template_resolver import (
    build_adaptive_routing_reward_writeback,
    build_rag_config_patch_hash,
    resolve_rag_config_template,
)
from app.services.rag_defaults import merge_rag_config_with_dataset_defaults
from app.services.structured_memory_service import build_structured_memory_context


@dataclass(frozen=True)
class PreparedChatRequestRuntime:
    effective_rag_config: Any
    dataset_id_used: UUID | None
    dataset_rag_defaults_applied_fields: list[str]
    effective_prompt_template_id: UUID | None
    effective_prompt_template_key: str | None
    effective_prompt_ab_experiment_key: str | None
    dataset_prompt_defaults_applied_fields: list[str]
    dataset_rag_config_template_defaults_applied_fields: list[str]
    rag_config_template_meta: dict[str, Any] | None
    history_for_llm: list[dict[str, Any]]


@dataclass(frozen=True)
class PreparedChatTurnSession:
    conversation: Conversation
    conversation_id: UUID
    scope_dataset_id: UUID | None
    allowed_doc_ids: list[UUID]
    long_term_messages: list[dict[str, Any]]


@dataclass(frozen=True)
class PreparedStreamChatRuntime:
    effective_rag_config: Any
    dataset_id_used: UUID | None
    dataset_rag_defaults_applied_fields: list[str]
    effective_prompt_template_id: UUID | None
    effective_prompt_template_key: str | None
    effective_prompt_ab_experiment_key: str | None
    dataset_prompt_defaults_applied_fields: list[str]
    dataset_rag_config_template_defaults_applied_fields: list[str]
    rag_config_template_meta: dict[str, Any] | None
    history_for_llm: list[dict[str, Any]]
    cache_feature_enabled: bool
    cache_key: str | None
    cache_skip_reason: str | None
    cache_eligible: bool
    cache_hit: bool
    full_response: str
    citations_data: list[Any]
    metrics_data: dict[str, Any]
    structured_data: object | None


def prepare_chat_turn_session(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: Any,
    allow_empty_docs: bool,
    allow_open_scope: bool,
    conversation_not_found_detail: str,
    dataset_required_detail: str,
    document_scope_mismatch_detail: str,
    empty_scope_detail: str,
) -> PreparedChatTurnSession:
    resolved_scope = resolve_chat_conversation_scope(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=request.conversation_id,
        request_document_ids=request.document_ids,
        request_dataset_id=request.dataset_id,
        request_message=request.message,
        allow_empty_docs=allow_empty_docs,
        allow_open_scope=allow_open_scope,
        conversation_not_found_detail=conversation_not_found_detail,
        dataset_required_detail=dataset_required_detail,
        document_scope_mismatch_detail=document_scope_mismatch_detail,
        empty_scope_detail=empty_scope_detail,
    )
    conversation = resolved_scope.conversation
    conversation_id = resolved_scope.conversation_id
    scope_dataset_id = resolved_scope.scope_dataset_id
    allowed_doc_ids = resolved_scope.allowed_doc_ids

    user_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="user",
        content=request.message,
        token_count=num_tokens_from_string(request.message or ""),
    )
    db.add(user_message)
    apply_auto_conversation_title(conversation, request.message)

    long_term_messages: list[dict[str, Any]] = []
    if (
        bool(getattr(request, "enable_long_term_memory", False))
        and bool(getattr(settings, "LONG_TERM_MEMORY_ENABLED", False))
        and conversation_id
    ):
        long_term_messages = _retrieve_long_term_messages(
            db=db,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            query=request.message,
            top_k=settings.LONG_TERM_MEMORY_TOP_K,
        )

    conversation.message_count = (conversation.message_count or 0) + 1
    db.commit()

    return PreparedChatTurnSession(
        conversation=conversation,
        conversation_id=conversation_id,
        scope_dataset_id=scope_dataset_id,
        allowed_doc_ids=allowed_doc_ids,
        long_term_messages=long_term_messages,
    )


def prepare_chat_request_runtime(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: Any,
    conversation_id: UUID | None,
    scope_dataset_id: UUID | None,
    document_ids: list[UUID],
    long_term_messages: list[dict[str, Any]],
    request_id: str,
) -> PreparedChatRequestRuntime:
    effective_rag_config = request.rag_config
    dataset_rag_defaults_applied_fields: list[str] = []
    dataset_defaults_meta: dict[str, Any] | None = None
    dataset_id_used: UUID | None = scope_dataset_id
    rag_fields_set = set(getattr(request.rag_config, "model_fields_set", set()) or set())
    if "rag_config" not in set(getattr(request, "model_fields_set", set()) or set()):
        rag_fields_set = set()
    try:
        if dataset_id_used is None:
            dataset_id_used = resolve_single_dataset_id_for_documents(
                db,
                tenant_id=tenant_id,
                document_ids=document_ids,
            )
        if dataset_id_used is not None:
            ds_meta = load_dataset_metadata(db, tenant_id=tenant_id, dataset_id=dataset_id_used)
            dataset_defaults_meta = ds_meta if isinstance(ds_meta, dict) else None
            raw_defaults = ds_meta.get("rag_defaults") if isinstance(ds_meta, dict) else None
            effective_rag_config, dataset_rag_defaults_applied_fields = merge_rag_config_with_dataset_defaults(
                rag_config=effective_rag_config,
                request_fields_set=rag_fields_set,
                raw_dataset_defaults=raw_defaults,
            )
    except Exception:
        dataset_rag_defaults_applied_fields = []
        dataset_defaults_meta = None
        dataset_id_used = scope_dataset_id

    req_fields = set(getattr(request, "model_fields_set", set()) or set())
    (
        effective_prompt_template_id,
        effective_prompt_template_key,
        effective_prompt_ab_experiment_key,
        dataset_prompt_defaults_applied_fields,
    ) = merge_prompt_defaults_with_dataset(
        prompt_template_id=request.prompt_template_id,
        prompt_template_key=request.prompt_template_key,
        prompt_ab_experiment_key=request.prompt_ab_experiment_key,
        request_fields_set=req_fields,
        dataset_meta=dataset_defaults_meta,
    )

    (
        effective_rag_config_template_id,
        effective_rag_config_template_key,
        effective_rag_config_ab_experiment_key,
        dataset_rag_config_template_defaults_applied_fields,
    ) = merge_rag_config_template_defaults_with_dataset(
        rag_config_template_id=request.rag_config_template_id,
        rag_config_template_key=request.rag_config_template_key,
        rag_config_ab_experiment_key=request.rag_config_ab_experiment_key,
        request_fields_set=req_fields,
        dataset_meta=dataset_defaults_meta,
    )

    rag_config_template_meta: dict[str, Any] | None = None
    rag_config_template_resolver_debug: dict[str, Any] | None = None
    rag_config_template_patch_applied_fields: list[str] = []
    try:
        if (
            effective_rag_config_template_id
            or (effective_rag_config_template_key or "").strip()
            or (effective_rag_config_ab_experiment_key or "").strip()
        ):
            chosen, rag_config_template_resolver_debug = resolve_rag_config_template(
                db=db,
                tenant_id=tenant_id,
                rag_config_template_id=effective_rag_config_template_id,
                template_key=effective_rag_config_template_key,
                ab_experiment_key=effective_rag_config_ab_experiment_key,
                ab_user_key=account_id,
                return_debug_metadata=True,
            )
            if chosen:
                effective_rag_config, rag_config_template_patch_applied_fields = apply_rag_config_patch(
                    rag_config=effective_rag_config,
                    patch=getattr(chosen, "config_patch", None),
                    request_fields_set=rag_fields_set,
                )
                rag_config_template_meta = {
                    "template_id": str(chosen.id),
                    "template_key": getattr(chosen, "template_key", None),
                    "version": int(getattr(chosen, "version", 0) or 0),
                    "ab_experiment_key": getattr(chosen, "ab_experiment_key", None),
                    "ab_variant": getattr(chosen, "ab_variant", None),
                    "patch_hash": build_rag_config_patch_hash(getattr(chosen, "config_patch", None)),
                    "patch_applied_fields": rag_config_template_patch_applied_fields,
                }
                if rag_config_template_resolver_debug:
                    rag_config_template_meta["resolver_debug"] = rag_config_template_resolver_debug
                    strategy = str(rag_config_template_resolver_debug.get("strategy") or "").strip().lower()
                    if strategy == "adaptive_epsilon_greedy":
                        rag_config_template_meta["reward_writeback"] = build_adaptive_routing_reward_writeback(
                            experiment_key=(
                                getattr(chosen, "ab_experiment_key", None) or effective_rag_config_ab_experiment_key
                            ),
                            variant=getattr(chosen, "ab_variant", None),
                            strategy=rag_config_template_resolver_debug.get("strategy"),
                            decision=rag_config_template_resolver_debug.get("decision"),
                            request_id=str(request_id),
                            template_id=str(chosen.id),
                            template_key=getattr(chosen, "template_key", None),
                        )

                try:
                    chosen.usage_count = int(getattr(chosen, "usage_count", 0) or 0) + 1
                    db.commit()
                except Exception:
                    with contextlib.suppress(Exception):
                        db.rollback()
    except Exception:
        rag_config_template_meta = None

    history_for_llm = [m.model_dump() for m in request.history] + long_term_messages
    if bool(getattr(request, "enable_summary_memory", False)) and conversation_id:
        try:
            summary_text = get_conversation_summary(db, tenant_id=tenant_id, conversation_id=conversation_id)
        except Exception:
            summary_text = None
        if summary_text:
            history_for_llm = [{"role": "system", "content": summary_text}] + history_for_llm

    if (
        bool(getattr(request, "enable_structured_memory", False))
        and bool(getattr(settings, "STRUCTURED_MEMORY_ENABLED", False))
        and conversation_id
    ):
        try:
            records = _retrieve_structured_memory_records(
                db=db,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                max_messages=int(getattr(settings, "STRUCTURED_MEMORY_LOOKBACK_MESSAGES", 80) or 80),
            )
            ctx = build_structured_memory_context(
                records=records,
                max_entities=int(getattr(settings, "STRUCTURED_MEMORY_MAX_ENTITIES", 20) or 20),
                max_facts=int(getattr(settings, "STRUCTURED_MEMORY_MAX_FACTS", 8) or 8),
                max_chars=int(getattr(settings, "STRUCTURED_MEMORY_MAX_CONTEXT_CHARS", 1200) or 1200),
            )
        except Exception:
            ctx = ""
        if ctx:
            history_for_llm = [{"role": "system", "content": ctx}] + history_for_llm

    return PreparedChatRequestRuntime(
        effective_rag_config=effective_rag_config,
        dataset_id_used=dataset_id_used,
        dataset_rag_defaults_applied_fields=dataset_rag_defaults_applied_fields,
        effective_prompt_template_id=effective_prompt_template_id,
        effective_prompt_template_key=effective_prompt_template_key,
        effective_prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
        dataset_prompt_defaults_applied_fields=dataset_prompt_defaults_applied_fields,
        dataset_rag_config_template_defaults_applied_fields=dataset_rag_config_template_defaults_applied_fields,
        rag_config_template_meta=rag_config_template_meta,
        history_for_llm=history_for_llm,
    )


def prepare_stream_chat_runtime(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    request: Any,
    conversation_id: UUID | None,
    scope_dataset_id: UUID | None,
    document_ids: list[UUID],
    long_term_messages: list[dict[str, Any]],
    request_id: str,
) -> PreparedStreamChatRuntime:
    request_runtime = prepare_chat_request_runtime(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        conversation_id=conversation_id,
        scope_dataset_id=scope_dataset_id,
        document_ids=document_ids,
        long_term_messages=long_term_messages,
        request_id=request_id,
    )

    effective_rag_config = request_runtime.effective_rag_config
    dataset_id_used = request_runtime.dataset_id_used
    effective_prompt_template_id = request_runtime.effective_prompt_template_id
    effective_prompt_template_key = request_runtime.effective_prompt_template_key
    effective_prompt_ab_experiment_key = (
        request_runtime.effective_prompt_ab_experiment_key
    )
    rag_config_template_meta = request_runtime.rag_config_template_meta
    history_for_llm = request_runtime.history_for_llm

    cache_scope_dataset_id = dataset_id_used or scope_dataset_id
    rag_cfg = jsonable_encoder(effective_rag_config.model_dump())
    prompt_cfg = {
        "prompt_template_id": str(effective_prompt_template_id)
        if effective_prompt_template_id
        else None,
        "prompt_template_key": (effective_prompt_template_key or None),
        "prompt_ab_experiment_key": (effective_prompt_ab_experiment_key or None),
    }
    cache_feature_enabled, cache_key, cache_skip_reason = prepare_chat_cache_lookup(
        db=db,
        tenant_id=tenant_id,
        account_id=str(account_id or ""),
        dataset_id=cache_scope_dataset_id,
        document_ids=document_ids,
        history=request.history,
        enable_long_term_memory=bool(request.enable_long_term_memory),
        long_term_messages=long_term_messages,
        enable_structured_memory=bool(getattr(request, "enable_structured_memory", False)),
        question=request.message,
        rag_config=rag_cfg,
        prompt_config=prompt_cfg,
        structured_output=bool(request.structured_output),
        structured_preset=request.structured_preset,
        use_graph=bool(effective_rag_config.use_graph),
    )
    cache_eligible = bool(cache_key)
    cached = get_cached_chat_response(cache_key) if cache_key else None

    full_response = ""
    citations_data: list[Any] = []
    metrics_data: dict[str, Any] = {}
    structured_data: object | None = None
    cache_hit = False

    if isinstance(cached, dict):
        full_response = str(cached.get("content") or "")
        citations_data = (
            cached.get("citations")
            if isinstance(cached.get("citations"), list)
            else []
        )
        metrics_data = annotate_chat_cache_metrics(
            dict(cached.get("metrics") or {}),
            enabled=cache_feature_enabled,
            hit=True,
            skip_reason=None,
        )
        structured_data = cached.get("structured_data")
        cache_hit = True

    return PreparedStreamChatRuntime(
        effective_rag_config=effective_rag_config,
        dataset_id_used=dataset_id_used,
        dataset_rag_defaults_applied_fields=request_runtime.dataset_rag_defaults_applied_fields,
        effective_prompt_template_id=effective_prompt_template_id,
        effective_prompt_template_key=effective_prompt_template_key,
        effective_prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
        dataset_prompt_defaults_applied_fields=request_runtime.dataset_prompt_defaults_applied_fields,
        dataset_rag_config_template_defaults_applied_fields=request_runtime.dataset_rag_config_template_defaults_applied_fields,
        rag_config_template_meta=rag_config_template_meta,
        history_for_llm=history_for_llm,
        cache_feature_enabled=cache_feature_enabled,
        cache_key=cache_key,
        cache_skip_reason=cache_skip_reason,
        cache_eligible=cache_eligible,
        cache_hit=cache_hit,
        full_response=full_response,
        citations_data=citations_data,
        metrics_data=metrics_data,
        structured_data=structured_data,
    )
