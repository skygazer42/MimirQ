from __future__ import annotations

import uuid

from app.api.schemas.chat import ChatRAGConfig
from app.services.rag_config_template_apply import apply_rag_config_patch
from app.services.rag_config_template_defaults import merge_rag_config_template_defaults_with_dataset
from app.services.rag_config_template_resolver import build_rag_config_patch_hash


def test_rag_config_template_defaults_prefer_id_over_key() -> None:
    ds_meta = {
        "default_rag_config_template_id": str(uuid.uuid4()),
        "default_rag_config_template_key": "retrieval_default",
        "default_rag_config_ab_experiment_key": "exp-1",
    }
    tid, key, ab, applied = merge_rag_config_template_defaults_with_dataset(
        rag_config_template_id=None,
        rag_config_template_key=None,
        rag_config_ab_experiment_key=None,
        request_fields_set=set(),
        dataset_meta=ds_meta,
    )
    assert tid is not None
    assert key is None  # key not applied because id won
    assert ab == "exp-1"
    assert set(applied) == {"rag_config_template_id", "rag_config_ab_experiment_key"}


def test_rag_config_template_defaults_respects_explicit_null() -> None:
    ds_meta = {"default_rag_config_template_key": "retrieval_default"}
    tid, key, ab, applied = merge_rag_config_template_defaults_with_dataset(
        rag_config_template_id=None,
        rag_config_template_key=None,  # explicit null in request
        rag_config_ab_experiment_key=None,
        request_fields_set={"rag_config_template_key"},
        dataset_meta=ds_meta,
    )
    assert tid is None
    assert key is None
    assert ab is None
    assert applied == []


def test_apply_rag_config_patch_does_not_override_explicit_request_fields_and_normalizes() -> None:
    base = ChatRAGConfig(top_k=5, retrieval_mode="hybrid")
    patched, applied = apply_rag_config_patch(
        rag_config=base,
        patch={"top_k": 12, "retrieval_mode": "semantic"},  # semantic -> vector (normalized)
        request_fields_set={"top_k"},
    )
    assert patched.top_k == 5
    assert patched.retrieval_mode == "vector"
    assert set(applied) == {"retrieval_mode"}


def test_build_rag_config_patch_hash_is_stable_and_ignores_nulls() -> None:
    h1 = build_rag_config_patch_hash({"top_k": 10, "score_threshold": None})
    h2 = build_rag_config_patch_hash({"score_threshold": None, "top_k": 10})
    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) == 16

