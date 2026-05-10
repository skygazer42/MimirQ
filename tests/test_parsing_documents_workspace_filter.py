from __future__ import annotations

from pathlib import Path


def test_parsing_documents_list_filters_workspace_metadata() -> None:
    src = Path("app/api/v1/parsing.py").read_text()

    assert 'DBDocument.doc_metadata["workspace"].astext == "parsing"' in src
    assert "query = _filter_parsing_workspace_documents(query)" in src
