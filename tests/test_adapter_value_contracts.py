import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.rag.kg.api.routes_support.merge_alias import _vector_alias_suggestions
from app.rag.kg.models import KgEntity


@pytest.mark.parametrize("user,password", [("", ""), ("milvus-user", "milvus-password")])
def test_milvus_status_passes_configured_credentials_to_sdk(
    monkeypatch: pytest.MonkeyPatch, user: str, password: str
) -> None:
    from app.api.v1 import settings as settings_api

    calls = []

    class Connections:
        def connect(self, **kwargs):
            calls.append(("connect", kwargs))

        def disconnect(self, alias):
            calls.append(("disconnect", alias))

    monkeypatch.setitem(sys.modules, "pymilvus", SimpleNamespace(connections=Connections()))
    monkeypatch.setattr(settings_api.settings, "MILVUS_USER", user)
    monkeypatch.setattr(settings_api.settings, "MILVUS_PASSWORD", password)

    result = settings_api._get_milvus_status()

    assert result == {"connected": True, "message": "connected"}
    assert calls[0][1]["user"] == user
    assert calls[0][1]["password"] == password
    assert calls[1] == ("disconnect", "status_check")


@pytest.mark.parametrize("entity_type", ["", "Person"])
def test_alias_vector_search_uses_actual_entity_type_with_tenant_filter(
    monkeypatch: pytest.MonkeyPatch, entity_type: str
) -> None:
    from app.rag.kg import repository

    tenant_id = uuid4()
    expressions = []

    class VectorIndex:
        def search(self, *, query_vector, top_k, expr):
            assert query_vector == [0.1, 0.2]
            assert top_k == 3
            expressions.append(expr)
            return []

    monkeypatch.setattr(repository, "get_milvus_adapter", lambda **_kwargs: VectorIndex())
    entity = KgEntity(id=uuid4(), tenant_id=tenant_id, type=entity_type, vector=[0.1, 0.2])

    response = _vector_alias_suggestions(object(), tenant_id=tenant_id, entity=entity, resolved_id=entity.id, want_k=3)

    assert response.stats["returned"] == 0
    assert response.suggestions == []
    assert len(expressions) == 1
    assert str(tenant_id) in expressions[0]
    if entity_type:
        assert 'type == "Person"' in expressions[0]
    else:
        assert "type ==" not in expressions[0]
