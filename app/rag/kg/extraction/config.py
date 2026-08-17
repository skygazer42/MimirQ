from uuid import UUID

from pydantic import Field, model_validator

from app.rag.kg.schemas import KGBaseModel
from app.rag.pipeline_plugins.refs import clean_python_plugin_ref


def _clean_kg_python_param_item(key: object, value: object) -> tuple[str, object] | None:
    if not isinstance(key, str):
        raise ValueError("kg_python_params keys must be strings")
    cleaned_key = key.strip()
    if not cleaned_key:
        return None
    if len(cleaned_key) > 80:
        raise ValueError("kg_python_params key too long (max=80)")
    if value is None or isinstance(value, (bool, int, float)):
        return cleaned_key, value
    if isinstance(value, str):
        if len(value) > 500:
            raise ValueError("kg_python_params string value too long (max=500)")
        return cleaned_key, value
    raise ValueError("kg_python_params values must be JSON primitives")


def _clean_kg_python_params(raw: object) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("kg_python_params must be an object")
    if len(raw) > 30:
        raise ValueError("kg_python_params has too many keys (max=30)")

    cleaned: dict = {}
    for key, value in raw.items():
        item = _clean_kg_python_param_item(key, value)
        if item is None:
            continue
        cleaned_key, cleaned_value = item
        cleaned[cleaned_key] = cleaned_value
    return cleaned or None


def _clean_kg_python_plugin(raw: object) -> str | None:
    return clean_python_plugin_ref(
        raw,
        field_name="kg_python_plugin",
        expected_stage="kg",
        invalid_message="kg_python_plugin must be an import path or registered KG plugin ref",
        file_path_message="kg_python_plugin must be an import path or registered KG plugin ref",
        disabled_import_message="kg_python_plugin import refs are disabled; use plugin:<id>@<version>:kg",
    )


class ExtractConfig(KGBaseModel):
    """Configuration for event extraction from document chunks."""

    chunk_ids: list[UUID] = Field(default_factory=list, description="DocumentChunk IDs to process")
    tenant_id: UUID | None = None
    max_concurrency: int = 3
    source_config_id: str | None = None
    replace_existing: bool = Field(default=True, description="Replace previously extracted events for these chunks")
    prune_orphan_entities: bool = Field(default=True, description="Prune entities with no remaining event links")
    # Optional toggles (default to settings when None).
    extract_relations: bool | None = Field(default=None, description="Extract entity relations (triples) if enabled")
    extract_skills: bool | None = Field(default=None, description="Extract Skill/SOP entities if enabled")
    # Optional PromptTemplate selectors (tenant-scoped).
    prompt_template_id: UUID | None = None
    prompt_template_key: str | None = None
    prompt_ab_experiment_key: str | None = None
    ab_user_key: str | None = None
    extraction_backend: str | None = Field(default=None, description="Extraction backend override: llm|gliner|hybrid|heuristic")
    kg_python_plugin: str | None = Field(
        default=None,
        description="Registered KG plugin ref; legacy module:function refs require PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES.",
    )
    kg_python_params: dict | None = Field(default=None, description="Optional params passed to the KG pipeline plugin")

    @model_validator(mode="after")
    def _validate_kg_python_params(self) -> "ExtractConfig":
        self.kg_python_plugin = _clean_kg_python_plugin(self.kg_python_plugin)
        self.kg_python_params = _clean_kg_python_params(self.kg_python_params)
        return self


# Legacy compatibility alias
ExtractBaseConfig = ExtractConfig
