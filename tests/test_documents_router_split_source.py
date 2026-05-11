from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_mineru_batch_upload_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_batch_upload.py")

    assert "from app.api.v1 import document_batch_upload" in documents_source
    assert "router.include_router(document_batch_upload.router)" in documents_source

    split_route_decorators = (
        '@router.post("/batch-upload/apply-urls"',
        '@router.get("/batch-upload/status/{batch_id}"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_mineru_batch_upload_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/batch-upload/apply-urls", ("POST",)) in routes
    assert ("/batch-upload/status/{batch_id}", ("GET",)) in routes


def test_folder_tree_route_is_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_folders.py")

    assert "from app.api.v1 import document_batch_upload, document_folders" in documents_source
    assert "router.include_router(document_folders.router)" in documents_source
    assert '@router.get("/folders"' not in documents_source
    assert '@router.get("/folders"' in split_source


def test_documents_router_still_exposes_folder_tree_route() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/folders", ("GET",)) in routes


def test_document_stats_route_is_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_stats.py")

    assert "from app.api.v1 import document_batch_upload, document_folders, document_stats" in documents_source
    assert "router.include_router(document_stats.router)" in documents_source
    assert '@router.get("/stats"' not in documents_source
    assert '@router.get("/stats"' in split_source


def test_documents_router_still_exposes_stats_route() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/stats", ("GET",)) in routes
