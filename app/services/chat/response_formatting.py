import logging
import re
from typing import Any
from uuid import UUID

logger = logging.getLogger("services.chat_runtime")


def apply_chat_runtime_metrics_context(
    metrics: dict[str, Any] | None,
    *,
    dataset_id_used: UUID | None,
    effective_prompt_template_id: UUID | None = None,
    effective_prompt_template_key: str | None = None,
    effective_prompt_ab_experiment_key: str | None = None,
    dataset_rag_defaults_applied_fields: list[str] | None = None,
    dataset_rag_config_template_defaults_applied_fields: list[str] | None = None,
    rag_config_template_meta: dict[str, Any] | None = None,
    dataset_prompt_defaults_applied_fields: list[str] | None = None,
    tenant_qps_meta: dict[str, Any] | None = None,
    quota_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict((metrics if metrics is not None else {}))
    if dataset_id_used is not None:
        out.setdefault("dataset_id", str(dataset_id_used))
    if effective_prompt_template_id is not None:
        out.setdefault("prompt_template_id", str(effective_prompt_template_id))
    if effective_prompt_template_key:
        out.setdefault("prompt_template_key", effective_prompt_template_key)
    if effective_prompt_ab_experiment_key:
        out.setdefault("prompt_ab_experiment_key", effective_prompt_ab_experiment_key)
    if rag_config_template_meta:
        out.setdefault("rag_config_template", rag_config_template_meta)
    if tenant_qps_meta is not None and tenant_qps_meta["enabled"]:
        out.setdefault("tenant_qps_quota", tenant_qps_meta)
    if quota_meta is not None and quota_meta["enabled"]:
        out.setdefault("quota", quota_meta)

    if dataset_rag_defaults_applied_fields:
        out.setdefault("dataset_rag_defaults_applied", True)
        out.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)
    if dataset_rag_config_template_defaults_applied_fields:
        out.setdefault("dataset_rag_config_template_defaults_applied", True)
        out.setdefault(
            "dataset_rag_config_template_defaults_fields", dataset_rag_config_template_defaults_applied_fields
        )
    if dataset_prompt_defaults_applied_fields:
        out.setdefault("dataset_prompt_defaults_applied", True)
        out.setdefault("dataset_prompt_defaults_fields", dataset_prompt_defaults_applied_fields)
    return out


def parse_graph_structured_output(
    *,
    content: str,
    structured_output: bool,
    structured_preset: str | None,
    metrics: dict[str, Any],
) -> object | None:
    if not structured_output:
        return None

    from app.rag.llm.response_parsing import parse_json_from_text

    structured_data, parse_meta = parse_json_from_text(content, expected="object")
    metrics["structured_parse_ok"] = bool(parse_meta.get("ok"))
    metrics["structured_parse_method"] = parse_meta.get("method")
    metrics["structured_parse_error"] = parse_meta.get("error")
    metrics["structured_type"] = type(structured_data).__name__ if structured_data is not None else None
    metrics["structured_preset"] = structured_preset
    return structured_data


def format_stream_error_message(exc: Exception) -> str:
    raw = str(exc) or exc.__class__.__name__
    raw = " ".join(raw.split())
    raw = re.sub(r"sk-[A-Za-z0-9]{8,}", "sk-***", raw)
    raw = re.sub(r"(?i)bearer\s+[A-Z0-9\-_.]{8,}", "Bearer ***", raw)
    status_code = getattr(exc, "status_code", None)
    if status_code and isinstance(status_code, int):
        raw = f"HTTP {status_code}: {raw}"
    return raw.strip()
