from __future__ import annotations

from pathlib import Path


def test_parsing_documents_list_filters_workspace_metadata() -> None:
    src = Path("app/api/v1/parsing.py").read_text()

    assert 'DBDocument.doc_metadata["workspace"].astext == "parsing"' in src
    assert "query = _filter_parsing_workspace_documents(query)" in src


def test_parsing_dataset_scope_uses_target_metadata_not_ingestion_dataset() -> None:
    src = Path("app/api/v1/parsing.py").read_text()

    assert 'DBDocument.doc_metadata["target_dataset_id"].astext == str(dataset_id)' in src
    assert 'meta["target_dataset_id"] = str(target_dataset.id)' in src
    assert 'meta["target_dataset_name"] = str(target_dataset.name or target_dataset.id)' in src
    assert "dataset_id=dataset.id" in src
