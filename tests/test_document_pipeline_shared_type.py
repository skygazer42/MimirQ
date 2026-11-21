def test_document_pipeline_options_is_shared_between_api_and_service_types() -> None:
    from app.api.schemas.documents.document import DocumentPipelineOptions as ApiPipelineOptions
    from app.api.schemas.documents.document import DocumentPipelineOptions as SharedPipelineOptions

    assert ApiPipelineOptions is SharedPipelineOptions
    request = ApiPipelineOptions(chunk_vector_enabled=False)
    assert request.chunk_vector_enabled is False
    assert "chunk_vector_enabled" in request.model_fields_set
