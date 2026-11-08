"""Typed ingestion policy selection, profile composition and pipeline resolution."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.document import DocumentPipelineOptions
from app.api.schemas.document_ingestion import PipelineOptionOverrides
from app.api.schemas.ingestion_policy import IngestionPolicy, IngestionRule
from app.api.utils.document_pipeline_input import to_pipeline_options, validate_chunk_params
from app.core.config import settings
from app.models.dataset import Dataset
from app.parsing.factory import parser_factory
from app.rag.chunking.factory import chunker_factory
from app.services.ingestion_policy import (
    ResolvedGovernanceProfilePatch,
    match_ingestion_rule,
    parse_ingestion_policy_from_metadata,
    resolve_governance_profile_ref,
)
from app.services.pipeline_config import merge_pipeline_options, resolve_pipeline_effective
from app.types.pipeline import PipelineOptions


@dataclass(frozen=True)
class UploadDefaultSelection:
    parser_backend_base: str
    chunk_strategy_base: str
    default_parser_backend: str
    default_chunk_strategy: str


@dataclass(frozen=True)
class ResolvedUploadPipeline:
    pipeline_options: PipelineOptions
    ingestion_meta: dict[str, Any] | None
    resolved_parser_backend: str
    resolved_chunk_strategy: str


@dataclass(frozen=True)
class ResolvedDocumentIngestionPolicy:
    parser_backend_choice: str
    chunk_strategy_choice: str
    pipeline_options: PipelineOptions
    ingestion_meta: dict[str, Any] | None


@dataclass(frozen=True)
class ResolvedDocumentPipeline:
    parser_backend: str
    chunk_strategy: str


@dataclass(frozen=True)
class PreparedDocumentIngestion:
    policy: ResolvedDocumentIngestionPolicy
    pipeline: ResolvedDocumentPipeline


def _global_defaults() -> tuple[str, str]:
    return (
        settings.DEFAULT_PARSER_BACKEND.strip().lower() or "auto",
        settings.DEFAULT_CHUNK_STRATEGY.strip().lower() or "langchain_recursive",
    )


def _normalized_dataset_default(value: object) -> str | None:
    # Dataset metadata is JSON; unlike an IngestionRule its values have no
    # per-key schema until this boundary reads them.
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized if normalized else None


def dataset_upload_defaults(dataset_meta: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if dataset_meta is None:
        return None, None
    return (
        _normalized_dataset_default(dataset_meta.get("default_parser_backend")),
        _normalized_dataset_default(dataset_meta.get("default_chunk_strategy")),
    )


def select_upload_defaults(
    *,
    parser_backend: str,
    chunk_strategy: str,
    dataset_default_pb: str | None,
    dataset_default_cs: str | None,
) -> UploadDefaultSelection:
    global_pb, global_cs = _global_defaults()
    selected_pb = (
        dataset_default_pb
        if dataset_default_pb and parser_backend.strip().lower() in {"", "auto", global_pb}
        else parser_backend
    )
    selected_cs = (
        dataset_default_cs
        if dataset_default_cs and chunk_strategy.strip().lower() in {"", global_cs}
        else chunk_strategy
    )
    return UploadDefaultSelection(
        selected_pb,
        selected_cs,
        (dataset_default_pb if dataset_default_pb else global_pb),
        (dataset_default_cs if dataset_default_cs else global_cs),
    )


def _apply_rule_defaults(
    *,
    matched_rule: IngestionRule,
    parser_backend_choice: str,
    chunk_strategy_choice: str,
    default_parser_backend: str,
    default_chunk_strategy: str,
) -> tuple[str, str]:
    if parser_backend_choice.strip().lower() in {"", "auto", default_parser_backend} and matched_rule.parser_backend:
        parser_backend_choice = matched_rule.parser_backend
    if chunk_strategy_choice.strip().lower() in {"", default_chunk_strategy} and matched_rule.chunk_strategy:
        chunk_strategy_choice = matched_rule.chunk_strategy
    return parser_backend_choice, chunk_strategy_choice


def _preprocess_steps(rule: IngestionRule) -> list[dict[str, Any]]:
    if not rule.preprocess.enabled:
        return []
    return [{"id": step.id, "params": dict(step.params)} for step in rule.preprocess.steps]


def _profile_patch(
    *,
    db: Session,
    tenant_id: UUID,
    rule: IngestionRule,
    cache: dict[str, ResolvedGovernanceProfilePatch] | None = None,
) -> tuple[dict[str, Any], str | None]:
    ref = rule.governance_profile_ref
    if not ref:
        return {}, None
    ref = ref.strip()
    resolved = cache.get(ref) if cache is not None else None
    if resolved is None:
        try:
            resolved = resolve_governance_profile_ref(db=db, tenant_id=tenant_id, profile_ref=ref)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid governance_profile_ref: {str(exc)[:120]}") from exc
        if cache is not None:
            cache[ref] = resolved
    patch = dict(resolved.pipeline_patch)
    if resolved.regex_rules:
        patch["governance_regex_rules"] = list(resolved.regex_rules)
    return patch, ref


def _ingestion_metadata(*, policy: IngestionPolicy, rule: IngestionRule, profile_ref: str | None) -> dict[str, Any]:
    steps = _preprocess_steps(rule)
    return {
        "version": policy.version,
        "rule": {"id": rule.id, "name": rule.name},
        "preprocess": {"enabled": bool(steps), "steps": steps},
        "governance_profile_ref": profile_ref,
    }


def resolve_parser_backend(*, file_ext: str, parser_backend_choice: str) -> str:
    if file_ext == ".pdf" and parser_backend_choice.strip().lower() in {"", "auto"}:
        return "auto"
    return parser_factory.resolve_backend(file_ext, parser_backend_choice)


def validate_pipeline_for_strategy(
    *,
    dataset_meta: dict[str, Any] | None,
    pipeline_options: PipelineOptions,
    resolved_chunk_strategy: str,
) -> None:
    effective = resolve_pipeline_effective(
        dataset_metadata=(dataset_meta if dataset_meta is not None else {}),
        document_metadata={},
        request_overrides=pipeline_options,
    )
    if resolved_chunk_strategy not in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        validate_chunk_params(effective.chunk_size, effective.chunk_overlap)


def resolve_upload_pipeline(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_meta: dict[str, Any] | None,
    policy: IngestionPolicy | None,
    filename: str,
    file_ext: str,
    pipeline_parsed: DocumentPipelineOptions | None,
    pipeline_overrides: PipelineOptionOverrides,
    defaults: UploadDefaultSelection,
    governance_profile_cache: dict[str, ResolvedGovernanceProfilePatch] | None = None,
) -> ResolvedUploadPipeline:
    pipeline_options = to_pipeline_options(pipeline=pipeline_parsed, overrides=pipeline_overrides)
    rule = match_ingestion_rule(policy, filename=filename, file_ext=file_ext)
    parser_choice, chunk_choice = defaults.parser_backend_base, defaults.chunk_strategy_base
    patch, metadata = PipelineOptions(), None
    if rule is not None:
        parser_choice, chunk_choice = _apply_rule_defaults(
            matched_rule=rule,
            parser_backend_choice=parser_choice,
            chunk_strategy_choice=chunk_choice,
            default_parser_backend=defaults.default_parser_backend,
            default_chunk_strategy=defaults.default_chunk_strategy,
        )
        profile, ref = _profile_patch(db=db, tenant_id=tenant_id, rule=rule, cache=governance_profile_cache)
        # Existing file uploads give the named profile precedence over the rule.
        patch = PipelineOptions(**{**rule.pipeline_patch, **profile})
        metadata = _ingestion_metadata(policy=policy, rule=rule, profile_ref=ref)
    pipeline_options = merge_pipeline_options(patch, pipeline_options)
    resolved_parser = resolve_parser_backend(file_ext=file_ext, parser_backend_choice=parser_choice)
    resolved_chunker = chunker_factory.resolve_strategy(chunk_choice)
    validate_pipeline_for_strategy(
        dataset_meta=dataset_meta, pipeline_options=pipeline_options, resolved_chunk_strategy=resolved_chunker
    )
    return ResolvedUploadPipeline(pipeline_options, metadata, resolved_parser, resolved_chunker)


def resolve_document_ingestion_policy(
    *,
    db: Session,
    tenant_id: UUID,
    dataset: Dataset,
    filename: str,
    file_ext: str,
    requested_parser_backend: str,
    requested_chunk_strategy: str,
    pipeline: DocumentPipelineOptions | None,
    source_url: str | None,
) -> ResolvedDocumentIngestionPolicy:
    pipeline_options = to_pipeline_options(pipeline=pipeline)
    policy = parse_ingestion_policy_from_metadata(dataset.dataset_metadata or {})
    rule = match_ingestion_rule(policy, filename=filename, file_ext=file_ext)
    dataset_pb, dataset_cs = dataset_upload_defaults(dataset.dataset_metadata)
    global_pb, global_cs = _global_defaults()
    default_pb, default_cs = dataset_pb or global_pb, dataset_cs or global_cs
    parser_choice = requested_parser_backend or default_pb
    chunk_choice = requested_chunk_strategy or default_cs
    patch, metadata = PipelineOptions(), None
    if rule is not None:
        parser_choice, chunk_choice = _apply_rule_defaults(
            matched_rule=rule,
            parser_backend_choice=parser_choice,
            chunk_strategy_choice=chunk_choice,
            default_parser_backend=default_pb,
            default_chunk_strategy=default_cs,
        )
        profile, ref = _profile_patch(db=db, tenant_id=tenant_id, rule=rule)
        # URL/HTML rules override their profile; preserve this established order.
        patch = PipelineOptions(**{**profile, **rule.pipeline_patch})
        metadata = {**_ingestion_metadata(policy=policy, rule=rule, profile_ref=ref), "source_url": source_url}
    return ResolvedDocumentIngestionPolicy(
        parser_choice, chunk_choice, merge_pipeline_options(patch, pipeline_options), metadata
    )


def resolve_document_pipeline(
    *,
    file_ext: str,
    parser_backend_choice: str,
    chunk_strategy_choice: str,
    preserve_pdf_auto: bool,
) -> ResolvedDocumentPipeline:
    try:
        parser = (
            resolve_parser_backend(file_ext=file_ext, parser_backend_choice=parser_backend_choice)
            if preserve_pdf_auto
            else parser_factory.resolve_backend(file_ext, parser_backend_choice)
        )
        chunker = chunker_factory.resolve_strategy(chunk_strategy_choice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ResolvedDocumentPipeline(parser, chunker)
