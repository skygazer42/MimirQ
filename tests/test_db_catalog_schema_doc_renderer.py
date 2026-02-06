from app.services.db_catalog_schema_doc_service import (
    build_virtual_schema_document_fields,
    chunk_virtual_schema_markdown,
    render_virtual_schema_markdown,
    virtual_schema_file_path,
    virtual_schema_filename,
)


def test_render_virtual_schema_markdown_includes_tables_and_columns():
    md = render_virtual_schema_markdown(
        dataset_id="00000000-0000-0000-0000-000000000000",
        tables=[
            {
                "engine": "mysql",
                "db_name": "demo",
                "schema_name": None,
                "table_name": "users",
                "table_type": "table",
                "comment": "user table",
                "columns": [
                    {"ordinal": 1, "name": "id", "data_type": "int", "nullable": False, "comment": None},
                    {"ordinal": 2, "name": "email", "data_type": "varchar", "nullable": True, "comment": None},
                ],
                "profile": {"row_count_estimate": 123},
            }
        ],
        generated_at_iso="2026-02-06T00:00:00+00:00",
    )

    assert "# Virtual DB Schema" in md
    assert "## demo.users" in md
    assert "`id`" in md
    assert "`email`" in md
    assert "row_count_estimate" in md


def test_render_virtual_schema_markdown_is_digest_only_no_raw_values():
    md = render_virtual_schema_markdown(
        dataset_id="00000000-0000-0000-0000-000000000000",
        tables=[
            {
                "engine": "mysql",
                "db_name": "demo",
                "schema_name": None,
                "table_name": "t",
                "table_type": "table",
                "comment": None,
                "columns": [{"ordinal": 1, "name": "ssn", "data_type": "varchar", "nullable": True, "comment": None}],
                "profile": {"sample_values": ["123-45-6789"]},
            }
        ],
        generated_at_iso="2026-02-06T00:00:00+00:00",
    )

    assert "123-45-6789" not in md


def test_virtual_schema_identity_helpers_are_stable_and_non_secret():
    dataset_id = "11111111-1111-1111-1111-111111111111"
    assert virtual_schema_file_path(dataset_id) == f"virtual://db_catalog/schema/{dataset_id}"
    assert virtual_schema_filename(dataset_id) == f"db_schema_{dataset_id}.md"


def test_build_virtual_schema_document_fields_sets_expected_metadata():
    doc = build_virtual_schema_document_fields(
        tenant_id="22222222-2222-2222-2222-222222222222",
        dataset_id="11111111-1111-1111-1111-111111111111",
        requested_by="acct_123",
        markdown="# Virtual DB Schema\n\nhello\n",
    )
    assert doc["file_type"] == "md"
    assert doc["file_path"] == "virtual://db_catalog/schema/11111111-1111-1111-1111-111111111111"
    assert doc["filename"] == "db_schema_11111111-1111-1111-1111-111111111111.md"
    assert doc["status"] == "completed"
    assert doc["current_stage"] == "completed"
    assert doc["doc_metadata"]["virtual_schema"] is True
    assert doc["doc_metadata"]["source"] == "db_catalog"
    assert doc["doc_metadata"]["doc_type_kwd"] == "db_schema"


def test_chunk_virtual_schema_markdown_produces_positioned_chunks():
    chunks = chunk_virtual_schema_markdown(
        markdown="# Virtual DB Schema\n\n## demo.users\n\n### Columns\n\n| ordinal | name | type |\n|---:|---|---|\n| 1 | `id` | int |\n",
        base_metadata={"source": "db_catalog", "doc_type_kwd": "db_schema"},
        chunk_size=200,
        chunk_overlap=0,
    )
    assert chunks
    assert chunks[0].start_char is not None
    assert chunks[0].end_char is not None
    assert chunks[0].metadata.get("chunk_strategy") == "markdown_outline"
