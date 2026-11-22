from pathlib import Path

from app.api.schemas.knowledge_graph import graph as kg_schemas
from app.api.v1.knowledge_graph import routes
from app.api.v1.knowledge_graph.routes_support import common, extraction, merge_alias, projection, undo
from app.api.v1.knowledge_graph.routes_support import types as schemas

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ROUTES_PATH = _REPO_ROOT / "app" / "api" / "v1" / "knowledge_graph" / "routes.py"


def _assert_route_dependencies(module: object, names: tuple[str, ...]) -> None:
    for name in names:
        assert getattr(routes, name) is getattr(module, name)


def test_routes_stays_within_line_budget() -> None:
    line_count = len(_ROUTES_PATH.read_text(encoding="utf-8").splitlines())
    assert line_count <= 2600, f"{_ROUTES_PATH.relative_to(_REPO_ROOT)} has {line_count} lines"


def test_routes_uses_common_and_extraction_owners() -> None:
    _assert_route_dependencies(common, ("KG_API_FALLBACK_LOG_MESSAGE", "KG_ENTITY_NOT_FOUND_DETAIL"))
    _assert_route_dependencies(
        extraction,
        ("_get_extraction_document", "_effective_kg_extraction_options", "_scope_chunks_to_pipeline"),
    )


def test_routes_uses_merge_and_alias_owner() -> None:
    _assert_route_dependencies(
        merge_alias,
        ("_merge_targets", "_offline_alias_suggestions", "_vector_alias_suggestions", "_commit_or_rollback"),
    )


def test_routes_uses_projection_owner_for_scope_and_graphs() -> None:
    _assert_route_dependencies(
        projection,
        ("_resolve_allowed_documents", "_apply_event_pipeline_scope", "_load_kg_projection_events"),
    )


def test_routes_uses_the_current_schema_owners() -> None:
    _assert_route_dependencies(schemas, ("KGExtractionOptions", "KGGraphProjectionParams"))
    _assert_route_dependencies(kg_schemas, ("KGGraphResponse", "KGEntityAliasSuggestionsResponse"))


def test_routes_uses_the_undo_owner() -> None:
    _assert_route_dependencies(
        undo,
        ("_get_applied_resolution_action", "_undo_merge_resolution_action", "_undo_split_resolution_action"),
    )
