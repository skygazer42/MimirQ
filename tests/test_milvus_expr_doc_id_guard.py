from __future__ import annotations

from uuid import uuid4

import pytest

from app.storage.vector.milvus import MilvusVectorStore


def test_milvus_build_expr_skips_doc_id_pushdown_when_too_many_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.MILVUS_EXPR_MAX_DOC_IDS", 2, raising=False)

    tenant_id = uuid4()
    doc_ids = [uuid4(), uuid4(), uuid4()]
    expr = MilvusVectorStore()._build_expr(document_ids=doc_ids, tenant_id=tenant_id)  # noqa: SLF001

    assert expr is not None
    assert f'tenant_id == \"{tenant_id}\"' in expr
    assert "document_id in" not in expr


def test_milvus_build_expr_includes_doc_id_pushdown_when_under_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.MILVUS_EXPR_MAX_DOC_IDS", 5, raising=False)

    tenant_id = uuid4()
    doc_ids = [uuid4(), uuid4()]
    expr = MilvusVectorStore()._build_expr(document_ids=doc_ids, tenant_id=tenant_id)  # noqa: SLF001

    assert expr is not None
    assert f'tenant_id == \"{tenant_id}\"' in expr
    assert "document_id in" in expr

