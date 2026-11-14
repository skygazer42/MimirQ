import pytest

from app.services.connector_reconcile_service import _normalize_refs
from app.services.connector_run_operations import _compact_string_list, _normalize_doc_access_mode
from app.services.connector_sync_state import normalize_boundary_ids, normalize_source_manifest
from app.services.corpus_cache_tokens import build_dataset_scope_corpus_cache_token
from app.services.document_identity import normalize_content_sha256


@pytest.mark.parametrize("value", [0, False])
def test_connector_manifests_preserve_provided_scalar_values(value):
    assert normalize_source_manifest({"source": value}) == {"source": str(value)}


@pytest.mark.parametrize("normalize", [normalize_boundary_ids, _normalize_refs, _compact_string_list])
def test_connector_identity_lists_keep_scalar_values_and_omit_only_absence(normalize):
    assert set(normalize([0, False, None, "source"])) == {"0", "False", "source"}


@pytest.mark.parametrize("value", [0, False])
def test_supplied_connector_mode_does_not_become_inherited_access(value):
    assert _normalize_doc_access_mode(value) == str(value).lower()


@pytest.mark.parametrize("value", [0, False])
def test_content_identity_keeps_actual_scalar_text(value):
    assert normalize_content_sha256(value) == str(value).lower()


@pytest.mark.parametrize("value", [0, False])
def test_supplied_dataset_identity_does_not_disable_the_corpus_token(value):
    assert build_dataset_scope_corpus_cache_token(dataset_id=value, updated_at=None) is not None


def test_actual_optional_identity_inputs_keep_no_identity_behavior():
    assert normalize_content_sha256(None) is None
    assert normalize_source_manifest({"source": None}) == {}
    assert build_dataset_scope_corpus_cache_token(dataset_id=None, updated_at=None) is None
