"""Canonical KG extraction options passed from API/ingest to queue workers."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

KG_EXTRACTION_JOB_OPTIONS_SCHEMA = "mimirq.kg_extraction_job_options.v1"


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_bool(value: object, *, field: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be a boolean or null")


def _required_bool(value: object, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be a boolean")


def _canonical_params(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("kg_python_params must be an object")
    try:
        normalized = json.loads(json.dumps(dict(value), ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise ValueError("kg_python_params must be JSON serializable") from exc
    if not isinstance(normalized, dict):
        raise ValueError("kg_python_params must be an object")
    return normalized


def build_kg_extraction_job_options(
    *,
    pipeline_hash: str | None,
    prompt_template_id: UUID | str | None,
    prompt_template_key: str | None,
    prompt_ab_experiment_key: str | None,
    extraction_backend: str | None,
    kg_python_plugin: str | None,
    kg_python_params: Mapping[str, Any] | None,
    replace_existing: bool,
    prune_orphan_entities: bool,
    extract_relations: bool | None,
    extract_skills: bool | None,
) -> dict[str, Any]:
    normalized_pipeline_hash = _optional_text(pipeline_hash)
    normalized_prompt_template_id = _optional_text(prompt_template_id)
    if normalized_prompt_template_id is not None:
        normalized_prompt_template_id = str(UUID(normalized_prompt_template_id))

    return {
        "schema": KG_EXTRACTION_JOB_OPTIONS_SCHEMA,
        "pipeline_hash": normalized_pipeline_hash,
        "prompt_template_id": normalized_prompt_template_id,
        "prompt_template_key": _optional_text(prompt_template_key),
        "prompt_ab_experiment_key": _optional_text(prompt_ab_experiment_key),
        "extraction_backend": _optional_text(extraction_backend),
        "kg_python_plugin": _optional_text(kg_python_plugin),
        "kg_python_params": _canonical_params(kg_python_params),
        "replace_existing": _required_bool(replace_existing, field="replace_existing"),
        "prune_orphan_entities": _required_bool(prune_orphan_entities, field="prune_orphan_entities"),
        "extract_relations": _optional_bool(extract_relations, field="extract_relations"),
        "extract_skills": _optional_bool(extract_skills, field="extract_skills"),
    }


def normalize_kg_extraction_job_options(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema") != KG_EXTRACTION_JOB_OPTIONS_SCHEMA:
        raise ValueError("unsupported KG extraction job options schema")
    return build_kg_extraction_job_options(
        pipeline_hash=_optional_text(value.get("pipeline_hash")),
        prompt_template_id=value.get("prompt_template_id"),
        prompt_template_key=_optional_text(value.get("prompt_template_key")),
        prompt_ab_experiment_key=_optional_text(value.get("prompt_ab_experiment_key")),
        extraction_backend=_optional_text(value.get("extraction_backend")),
        kg_python_plugin=_optional_text(value.get("kg_python_plugin")),
        kg_python_params=value.get("kg_python_params"),
        replace_existing=_required_bool(value.get("replace_existing"), field="replace_existing"),
        prune_orphan_entities=_required_bool(value.get("prune_orphan_entities"), field="prune_orphan_entities"),
        extract_relations=_optional_bool(value.get("extract_relations"), field="extract_relations"),
        extract_skills=_optional_bool(value.get("extract_skills"), field="extract_skills"),
    )


def kg_extraction_job_options_fingerprint(value: object) -> str:
    normalized = normalize_kg_extraction_job_options(value)
    raw = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]
