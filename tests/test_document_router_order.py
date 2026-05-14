from __future__ import annotations


def test_static_document_routes_are_registered_before_document_detail_route() -> None:
    from app.api.v1.documents import router

    paths = [getattr(route, "path", "") for route in router.routes]
    detail_index = paths.index("/{document_id}")

    for static_path in (
        "/dead-letters",
        "/duplicates",
        "/folders",
        "/manual",
        "/preview",
        "/stats",
    ):
        assert static_path in paths
        assert paths.index(static_path) < detail_index, f"{static_path} must be registered before /{{document_id}}"
