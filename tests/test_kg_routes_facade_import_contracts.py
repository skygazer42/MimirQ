from pathlib import Path

from app.rag.kg import schemas as kg_schemas
from app.rag.kg.api import routes
from app.rag.kg.api.routes_support import common, extraction, merge_alias, projection, schemas, undo

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ROUTES_PATH = _REPO_ROOT / "app" / "rag" / "kg" / "api" / "routes.py"


def _assert_routes_reexports(module: object, names: tuple[str, ...]) -> None:
    for name in names:
        assert getattr(routes, name) is getattr(module, name)


def test_routes_stays_within_line_budget() -> None:
    line_count = len(_ROUTES_PATH.read_text(encoding="utf-8").splitlines())
    assert line_count <= 2600, f"{_ROUTES_PATH.relative_to(_REPO_ROOT)} has {line_count} lines"


def test_routes_keeps_common_and_extraction_reexports() -> None:
    _assert_routes_reexports(
        common,
        (
            "KG_EXTRACTION_ALREADY_QUEUED_DETAIL",
            "KG_PIPELINE_CHUNKS_NOT_FOUND_DETAIL",
        ),
    )
    _assert_routes_reexports(
        extraction,
        (
            "_default_prompt_template_id",
            "_document_kg_python_plugin",
            "_selected_extraction_pipeline_hash",
        ),
    )


def test_routes_keeps_merge_alias_reexports() -> None:
    _assert_routes_reexports(
        merge_alias,
        (
            "_alias_suggestion_item",
            "_delete_duplicate_target_assocs",
            "_merge_duplicate_assoc_fields",
            "_score_alias_candidates",
            "_target_assoc_to_keep",
            "_vector_alias_suggestion_item",
        ),
    )


def test_routes_keeps_projection_reexports() -> None:
    _assert_routes_reexports(
        projection,
        (
            "_active_pipeline_hash_expr",
            "_add_kg_entity_cooccurrence_links",
            "_append_relation_links",
            "_apply_relation_pipeline_scope",
            "_chunk_matches_pipeline",
            "_dict_list",
            "_doc_pipeline_hash",
            "_event_entity_nodes_and_links",
            "_event_entity_snapshot",
            "_event_ids_for_center_entity",
            "_kg_allowed_entities",
            "_kg_entity_cooccurrence_counts",
            "_kg_entity_node",
            "_kg_event_degrees",
            "_kg_event_entity_link",
            "_kg_event_entity_rows",
            "_kg_event_node",
            "_kg_limit_value",
            "_kg_relation_link",
            "_load_events_by_ids",
            "_related_event_ids_for_center_event",
            "_relation_snapshot",
            "_uuid_list",
            "_uuid_or_none",
        ),
    )


def test_routes_keeps_schema_reexports() -> None:
    _assert_routes_reexports(
        schemas,
        (
            "KGExtractionEffectiveOptions",
            "KGGraphBuildResult",
            "KGGraphProjectionLimits",
            "KGMergeAffectedRows",
            "KGMergeSideEffects",
            "KGMergeTargets",
            "KGUndoStats",
        ),
    )
    _assert_routes_reexports(kg_schemas, ("KGEntityAliasSuggestionItem",))


def test_routes_keeps_undo_reexports() -> None:
    _assert_routes_reexports(
        undo,
        (
            "_delete_orphan_split_entity",
            "_dict_or_none",
            "_limited_optional_str",
            "_remove_merge_redirect",
            "_restore_deleted_assoc_rows",
            "_restore_deleted_relation_rows",
            "_restore_source_entity_vector_if_needed",
            "_restore_split_relations",
            "_restore_updated_assocs",
            "_restore_updated_relations",
            "_restored_relation_row_payload",
        ),
    )
