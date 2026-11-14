from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import index_audit_service as audit


def _summary(existing, checked):
    return audit.compute_index_audit_summary(
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        active_documents=1,
        active_chunks=1,
        vector_id_missing=0,
        vector_ids_checked=checked,
        vector_ids_existing=existing,
    )


def test_unavailable_vector_check_is_not_reported_as_all_missing() -> None:
    with pytest.raises(TypeError):
        _summary(None, ["vector"])
    assert _summary(set(), ["vector"])["vector_ids_missing_in_backend"] == 1
    assert _summary(None, [])["vector_ids_checked"] == 0


def test_vector_check_keeps_a_falsy_set_with_real_members() -> None:
    class Existing(set):
        def __bool__(self):
            return False

    assert _summary(Existing({"vector"}), ["vector"])["vector_ids_missing_in_backend"] == 0


def test_milvus_check_exposes_the_original_backend_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.storage.vector import milvus

    def unavailable(_ids):
        raise ConnectionError("vector backend unavailable")

    monkeypatch.setattr(milvus, "milvus_store", SimpleNamespace(fetch_existing_ids=unavailable))
    with pytest.raises(ConnectionError, match="vector backend unavailable"):
        audit._milvus_existing_vector_ids(["vector"])
