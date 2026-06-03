from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_mineru_batch_upload_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_batch_upload.py")

    assert "from app.api.v1 import (" in documents_source
    assert "document_batch_upload" in documents_source
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

    assert "from app.api.v1 import (" in documents_source
    assert "document_folders" in documents_source
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

    assert "from app.api.v1 import (" in documents_source
    assert "document_stats" in documents_source
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


def test_documents_router_registers_static_single_segment_routes_before_detail_route() -> None:
    from app.api.v1.documents import router

    ordered_paths = [getattr(route, "path", "") for route in router.routes]

    stats_idx = ordered_paths.index("/stats")
    detail_idx = ordered_paths.index("/{document_id}")

    assert stats_idx < detail_idx


def test_document_duplicates_route_is_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_duplicates.py")

    assert "from app.api.v1 import (" in documents_source
    assert "document_duplicates" in documents_source
    assert "router.include_router(document_duplicates.router)" in documents_source
    assert '@router.get("/duplicates"' not in documents_source
    assert '@router.get("/duplicates"' in split_source


def test_documents_router_still_exposes_duplicates_route() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/duplicates", ("GET",)) in routes


def test_document_versions_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_versions.py")

    assert "from app.api.v1 import (" in documents_source
    assert "document_versions" in documents_source
    assert "router.include_router(document_versions.router)" in documents_source

    split_route_decorators = (
        '@router.get("/{document_id}/versions"',
        '@router.get("/{document_id}/versions/diff"',
        '"/{document_id}/versions/{pipeline_hash}/activate"',
        '@router.delete("/{document_id}/versions/{pipeline_hash}"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_versions_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}/versions", ("GET",)) in routes
    assert ("/{document_id}/versions/diff", ("GET",)) in routes
    assert ("/{document_id}/versions/{pipeline_hash}/activate", ("POST",)) in routes
    assert ("/{document_id}/versions/{pipeline_hash}", ("DELETE",)) in routes


def test_document_lifecycle_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_lifecycle.py")

    assert "from app.api.v1 import (" in documents_source
    assert "document_lifecycle" in documents_source
    assert "router.include_router(document_lifecycle.router)" in documents_source

    split_route_decorators = (
        '@router.get("/{document_id}/lifecycle-metadata"',
        '@router.patch("/{document_id}/lifecycle-metadata"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_lifecycle_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}/lifecycle-metadata", ("GET",)) in routes
    assert ("/{document_id}/lifecycle-metadata", ("PATCH",)) in routes


def test_document_access_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_access.py")

    assert "from app.api.v1 import (" in documents_source
    assert "document_access" in documents_source
    assert "router.include_router(document_access.router)" in documents_source

    split_route_decorators = (
        '@router.get("/{document_id}/access"',
        '@router.put("/{document_id}/access"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_access_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}/access", ("GET",)) in routes
    assert ("/{document_id}/access", ("PUT",)) in routes


def test_document_timeline_route_is_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_timeline.py")

    assert "document_timeline" in documents_source
    assert "router.include_router(document_timeline.router)" in documents_source
    assert '@router.get("/{document_id}/timeline"' not in documents_source
    assert '@router.get("/{document_id}/timeline"' in split_source


def test_documents_router_still_exposes_timeline_route() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}/timeline", ("GET",)) in routes


def test_document_content_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_content.py")

    assert "document_content" in documents_source
    assert "router.include_router(document_content.router)" in documents_source

    split_route_decorators = (
        '@router.get("/{document_id}/parsed-content"',
        '@router.get("/{document_id}/clean-docx"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_content_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}/parsed-content", ("GET",)) in routes
    assert ("/{document_id}/clean-docx", ("GET",)) in routes


def test_document_preview_route_is_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_preview.py")

    assert "document_preview" in documents_source
    assert "router.include_router(document_preview.router)" in documents_source
    assert '@router.post("/preview"' not in documents_source
    assert '@router.post("/preview"' in split_source


def test_documents_router_still_exposes_preview_route() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/preview", ("POST",)) in routes


def test_document_chunk_preview_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_chunk_preview.py")

    assert "document_chunk_preview" in documents_source
    assert "router.include_router(document_chunk_preview.router)" in documents_source

    split_route_decorators = (
        '@router.post("/chunk-preview"',
        '@router.post("/chunk-preview/by-sha"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_chunk_preview_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/chunk-preview", ("POST",)) in routes
    assert ("/chunk-preview/by-sha", ("POST",)) in routes


def test_document_upload_route_delegates_to_split_module() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_upload.py")

    assert "document_upload" in documents_source
    assert "router.include_router(document_upload.router)" in documents_source
    assert '@router.post("/upload"' not in documents_source
    assert '@router.post("/upload"' in split_source


def test_document_upload_url_route_is_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_upload.py")

    assert "document_upload" in documents_source
    assert "router.include_router(document_upload.router)" in documents_source
    assert '@router.post("/upload-url"' not in documents_source
    assert '@router.post("/upload-url"' in split_source


def test_document_upload_batch_supports_precheck_only_without_creating_documents() -> None:
    split_source = _source("app/api/v1/document_upload.py")

    assert "precheck_only: bool = Form(False)" in split_source
    assert "if precheck_only:" in split_source
    assert "Precheck-only upload returns scan evidence without creating DBDocument rows" in split_source
    assert '"precheck_scan_run_id": str(scan_run.id) if scan_run is not None else None' in split_source
    assert "return {" in split_source
    assert '"successful": [],' in split_source


def test_document_upload_batch_supports_upload_only_without_enqueueing_processing() -> None:
    split_source = _source("app/api/v1/document_upload.py")

    assert "upload_only: bool = Form(False)" in split_source
    assert "upload_only = form.upload_only" in split_source
    assert "if upload_only:" in split_source
    assert 'doc_metadata["ingest_stage"] = "uploaded_only"' in split_source
    assert "Upload-only stores the source document but intentionally does not enqueue parsing" in split_source


def test_documents_router_still_exposes_upload_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/upload", ("POST",)) in routes
    assert ("/upload-url", ("POST",)) in routes


def test_document_detail_route_is_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_detail.py")

    assert "document_detail" in documents_source
    assert "router.include_router(document_detail.router)" in documents_source
    assert '@router.get("/{document_id}"' not in documents_source
    assert '@router.get("/{document_id}"' in split_source


def test_documents_router_still_exposes_detail_route() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}", ("GET",)) in routes


def test_document_health_route_is_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_health.py")

    assert "document_health" in documents_source
    assert "router.include_router(document_health.router)" in documents_source
    assert '@router.get("/{document_id}/health"' not in documents_source
    assert '@router.get("/{document_id}/health"' in split_source


def test_documents_router_still_exposes_health_route() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}/health", ("GET",)) in routes


def test_document_chunk_read_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_chunks_read.py")

    assert "document_chunks_read" in documents_source
    assert "router.include_router(document_chunks_read.router)" in documents_source

    split_route_decorators = (
        '@router.get("/{document_id}/chunks"',
        '@router.get("/{document_id}/chunks/matches"',
        '@router.get("/{document_id}/chunks/{chunk_id}"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_chunk_read_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}/chunks", ("GET",)) in routes
    assert ("/{document_id}/chunks/matches", ("GET",)) in routes
    assert ("/{document_id}/chunks/{chunk_id}", ("GET",)) in routes


def test_document_chunk_write_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_chunks_write.py")

    assert "document_chunks_write" in documents_source
    assert "router.include_router(document_chunks_write.router)" in documents_source

    split_route_decorators = (
        '"/{document_id}/chunks"',
        '"/{document_id}/chunks/{chunk_id}"',
        '"/{document_id}/chunks/{chunk_id}/disable"',
        '"/{document_id}/chunks/{chunk_id}/enable"',
        '"/{document_id}/chunks/reembed"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_chunk_write_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}/chunks", ("POST",)) in routes
    assert ("/{document_id}/chunks/{chunk_id}", ("PATCH",)) in routes
    assert ("/{document_id}/chunks/{chunk_id}", ("DELETE",)) in routes
    assert ("/{document_id}/chunks/{chunk_id}/disable", ("POST",)) in routes
    assert ("/{document_id}/chunks/{chunk_id}/enable", ("POST",)) in routes
    assert ("/{document_id}/chunks/reembed", ("POST",)) in routes


def test_document_mutation_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_mutations.py")

    assert "document_mutations" in documents_source
    assert "router.include_router(document_mutations.router)" in documents_source

    split_route_decorators = (
        '"/{document_id}/qa/generate"',
        '"/{document_id}/pipeline"',
        '"/{document_id}/metadata"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_mutation_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}/qa/generate", ("POST",)) in routes
    assert ("/{document_id}/pipeline", ("PATCH",)) in routes
    assert ("/{document_id}/metadata", ("PATCH",)) in routes


def test_document_processing_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_processing.py")

    assert "document_processing" in documents_source
    assert "router.include_router(document_processing.router)" in documents_source

    split_route_decorators = (
        '@router.get("/{document_id}/status"',
        '@router.post("/{document_id}/cancel"',
        '@router.post("/{document_id}/retry"',
        '@router.delete("/{document_id}"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_processing_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}/status", ("GET",)) in routes
    assert ("/{document_id}/cancel", ("POST",)) in routes
    assert ("/{document_id}/retry", ("POST",)) in routes
    assert ("/{document_id}", ("DELETE",)) in routes


def test_document_batch_management_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_batches.py")

    assert "document_batches" in documents_source
    assert "router.include_router(document_batches.router)" in documents_source

    split_route_decorators = (
        '@router.post("/batch/metadata"',
        '@router.post("/batch/retry"',
        '@router.post("/batch/reingest"',
        '@router.post("/batch/access"',
        '@router.post("/batch/move"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_batch_management_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/batch/metadata", ("POST",)) in routes
    assert ("/batch/retry", ("POST",)) in routes
    assert ("/batch/reingest", ("POST",)) in routes
    assert ("/batch/access", ("POST",)) in routes
    assert ("/batch/move", ("POST",)) in routes


def test_document_batch_lifecycle_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_batches_lifecycle.py")

    assert "document_batches_lifecycle" in documents_source
    assert "router.include_router(document_batches_lifecycle.router)" in documents_source

    split_route_decorators = (
        '@router.post("/batch/disable"',
        '@router.post("/batch/enable"',
        '@router.post("/batch/archive"',
        '@router.post("/batch/unarchive"',
        '@router.post("/batch-delete"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_batch_lifecycle_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/batch/disable", ("POST",)) in routes
    assert ("/batch/enable", ("POST",)) in routes
    assert ("/batch/archive", ("POST",)) in routes
    assert ("/batch/unarchive", ("POST",)) in routes
    assert ("/batch-delete", ("POST",)) in routes


def test_documents_list_route_is_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_listing.py")

    assert "document_listing" in documents_source
    assert "router.include_router(document_listing.router)" in documents_source
    assert '@router.get("/",' not in documents_source
    assert '@router.get("/",' in split_source


def test_documents_router_still_exposes_list_route() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/", ("GET",)) in routes


def test_document_asset_routes_are_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_assets.py")

    assert "document_assets" in documents_source
    assert "router.include_router(document_assets.router)" in documents_source

    split_route_decorators = (
        '@router.get("/{document_id}/download"',
        '@router.get("/image/{image_id}"',
        '@router.get("/image-url/{img_id}"',
    )
    for decorator in split_route_decorators:
        assert decorator not in documents_source
        assert decorator in split_source


def test_documents_router_still_exposes_asset_routes() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/{document_id}/download", ("GET",)) in routes
    assert ("/image/{image_id}", ("GET",)) in routes
    assert ("/image-url/{img_id}", ("GET",)) in routes


def test_document_manual_route_is_split_from_documents_router() -> None:
    documents_source = _source("app/api/v1/documents.py")
    split_source = _source("app/api/v1/document_manual.py")

    assert "document_manual" in documents_source
    assert "router.include_router(document_manual.router)" in documents_source
    assert '@router.post("/manual"' not in documents_source
    assert '@router.post("/manual"' in split_source


def test_document_manual_route_returns_before_background_indexing() -> None:
    split_source = _source("app/api/v1/document_manual.py")
    route_idx = split_source.index("async def create_document_with_manual_chunks")
    commit_idx = split_source.index("db.commit()", route_idx)
    task_idx = split_source.index("background_tasks.add_task(", route_idx)
    return_idx = split_source.index("return db_document", task_idx)

    assert "BackgroundTasks" in split_source
    assert "SessionLocal" in split_source
    assert "_process_manual_document_chunks_background" in split_source
    assert "current_stage=\"queued\"" in split_source
    assert commit_idx < task_idx < return_idx
    assert "Indexer(db).upsert(" not in split_source[route_idx:task_idx]


def test_documents_router_still_exposes_manual_route() -> None:
    from app.api.v1.documents import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/manual", ("POST",)) in routes
