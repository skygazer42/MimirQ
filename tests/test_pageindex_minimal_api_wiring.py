from __future__ import annotations

from pathlib import Path


def test_rag_api_exposes_minimal_pageindex_borrowed_surfaces() -> None:
    text = Path("app/api/v1/rag.py").read_text(encoding="utf-8")

    assert 'default="mimirq.tree_search_preview.v1"' in text
    assert '@router.post("/document-structure"' in text
    assert '@router.post("/tree-search-preview"' in text
    assert "DocumentStructureRequest" in text
    assert "TreeSearchPreviewRequest" in text
    assert "_attach_document_structure_trace" in text
    assert 'metrics.setdefault("document_structure_trace"' in text
