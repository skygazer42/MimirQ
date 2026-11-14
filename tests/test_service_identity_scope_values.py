from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.document import Document
from app.services.chat_persistence import _online_eval_retrieval_mode
from app.services.connector_reconcile_service import extract_connector_source_identity, plan_connector_reconcile
from app.services.fusion_weight_learning_service import _iter_filtered_traces


@pytest.mark.parametrize("trace_tenant", [None, "", "other-tenant"])
def test_selected_tenant_excludes_unowned_or_mismatched_traces(trace_tenant) -> None:
    rows = [{"event": "rag_trace", "tenant_id": trace_tenant}]
    assert _iter_filtered_traces(rows, tenant_id="selected-tenant") == []
    assert len(_iter_filtered_traces(rows, tenant_id=None)) == 1


def test_blank_config_selector_cannot_widen_reconcile_to_other_configs() -> None:
    document = Document(
        id=uuid4(), doc_metadata={"connector": {"connector_id": "url_batch", "config_id": "other", "source_ref": "url"}}
    )
    args = dict(connector_id="url_batch", dataset_id=None, documents=[document], desired_source_refs=[], apply=False)
    assert plan_connector_reconcile(**args, config_id="")["documents_considered"] == 0
    assert plan_connector_reconcile(**args, config_id=None)["documents_considered"] == 1


def test_connector_identity_does_not_replace_present_empty_values_with_aliases() -> None:
    identity = extract_connector_source_identity(
        SimpleNamespace(
            doc_metadata={"connector": {"connector_id": "", "config_id": "", "source_ref": "", "page_id": "legacy"}}
        )
    )
    assert identity["connector_id"] == ""
    assert identity["config_id"] == ""
    assert identity["source_ref"] == ""


@pytest.mark.parametrize("value", ["", 0, False, None])
def test_present_retrieval_mode_is_forwarded_without_default_selection(value) -> None:
    assert _online_eval_retrieval_mode({"retrieval_mode": value}, "hybrid") == value
    assert _online_eval_retrieval_mode({}, "hybrid") == "hybrid"
