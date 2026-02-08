from __future__ import annotations

from app.api.schemas.chat import ChatRAGConfig
from app.services.rag_defaults import merge_rag_config_with_dataset_defaults


def test_merge_rag_defaults_applies_when_field_not_provided():  # noqa: ANN001
    base = ChatRAGConfig(top_k=5, retrieval_mode="hybrid")
    effective, applied = merge_rag_config_with_dataset_defaults(
        rag_config=base,
        request_fields_set=set(),  # rag_config omitted -> nothing is "explicit"
        raw_dataset_defaults={"top_k": 12, "retrieval_mode": "semantic"},  # semantic -> vector (normalized)
    )
    assert effective.top_k == 12
    assert effective.retrieval_mode == "vector"
    assert set(applied) == {"top_k", "retrieval_mode"}


def test_merge_rag_defaults_does_not_override_explicit_request_fields():  # noqa: ANN001
    base = ChatRAGConfig(top_k=5, retrieval_mode="hybrid")
    effective, applied = merge_rag_config_with_dataset_defaults(
        rag_config=base,
        request_fields_set={"top_k"},
        raw_dataset_defaults={"top_k": 12, "retrieval_mode": "keyword"},
    )
    # top_k preserved; retrieval_mode updated because it wasn't explicitly provided.
    assert effective.top_k == 5
    assert effective.retrieval_mode == "keyword"
    assert set(applied) == {"retrieval_mode"}


def test_merge_rag_defaults_ignores_invalid_payload():  # noqa: ANN001
    base = ChatRAGConfig(top_k=5, retrieval_mode="hybrid")
    effective, applied = merge_rag_config_with_dataset_defaults(
        rag_config=base,
        request_fields_set=set(),
        raw_dataset_defaults="not-a-dict",
    )
    assert effective.top_k == 5
    assert applied == []


def test_merge_rag_defaults_applies_visible_evidence_only():  # noqa: ANN001
    base = ChatRAGConfig(top_k=5, retrieval_mode="hybrid")
    effective, applied = merge_rag_config_with_dataset_defaults(
        rag_config=base,
        request_fields_set=set(),
        raw_dataset_defaults={"visible_evidence_only": True},
    )
    assert effective.visible_evidence_only is True
    assert set(applied) == {"visible_evidence_only"}
