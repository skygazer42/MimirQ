from __future__ import annotations

import uuid

from app.core.pipeline_versions import (
    build_doc_pipeline_key,
    get_active_pipeline_hash,
    get_selected_pipeline_hash,
    resolve_doc_pipeline_key,
    should_preserve_existing_versions,
)


def test_get_active_pipeline_hash_prefers_active_pipeline_hash():
    meta = {"pipeline_hash": "old", "active_pipeline_hash": "active"}
    assert get_active_pipeline_hash(meta) == "active"


def test_get_active_pipeline_hash_falls_back_to_pipeline_hash():
    meta = {"pipeline_hash": "current"}
    assert get_active_pipeline_hash(meta) == "current"


def test_get_active_pipeline_hash_strips_and_returns_none_when_empty():
    assert get_active_pipeline_hash({"active_pipeline_hash": "   "}) is None
    assert get_active_pipeline_hash(None) is None


def test_get_selected_pipeline_hash_param_overrides_active():
    meta = {"active_pipeline_hash": "active"}
    assert get_selected_pipeline_hash(meta, "explicit") == "explicit"
    assert get_selected_pipeline_hash(meta, "  explicit  ") == "explicit"


def test_build_doc_pipeline_key():
    doc_id = uuid.uuid4()
    assert build_doc_pipeline_key(doc_id, "abc") == f"{doc_id}:abc"


def test_resolve_doc_pipeline_key_none_when_all_versions_true():
    doc_id = uuid.uuid4()
    meta = {"active_pipeline_hash": "active"}
    assert resolve_doc_pipeline_key(doc_id, meta, None, all_versions=True) is None


def test_resolve_doc_pipeline_key_uses_active_when_no_param():
    doc_id = uuid.uuid4()
    meta = {"active_pipeline_hash": "active"}
    assert resolve_doc_pipeline_key(doc_id, meta, None, all_versions=False) == f"{doc_id}:active"


def test_resolve_doc_pipeline_key_uses_param_when_provided():
    doc_id = uuid.uuid4()
    meta = {"active_pipeline_hash": "active"}
    assert resolve_doc_pipeline_key(doc_id, meta, "v2", all_versions=False) == f"{doc_id}:v2"


def test_resolve_doc_pipeline_key_none_when_no_hash_available():
    doc_id = uuid.uuid4()
    assert resolve_doc_pipeline_key(doc_id, {}, None, all_versions=False) is None


def test_should_preserve_existing_versions_true_when_active_ready_and_hash_differs():
    meta = {"active_pipeline_ready": True, "active_pipeline_hash": "old", "pipeline_hash": "new"}
    assert should_preserve_existing_versions(meta) is True


def test_should_preserve_existing_versions_false_when_not_active_ready_or_hash_missing_or_equal():
    assert should_preserve_existing_versions({"active_pipeline_ready": False, "active_pipeline_hash": "a", "pipeline_hash": "b"}) is False
    assert should_preserve_existing_versions({"active_pipeline_ready": True, "active_pipeline_hash": "", "pipeline_hash": "b"}) is False
    assert should_preserve_existing_versions({"active_pipeline_ready": True, "active_pipeline_hash": "a", "pipeline_hash": ""}) is False
    assert should_preserve_existing_versions({"active_pipeline_ready": True, "active_pipeline_hash": "same", "pipeline_hash": "same"}) is False
    assert should_preserve_existing_versions(None) is False
