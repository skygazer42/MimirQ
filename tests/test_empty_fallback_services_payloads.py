from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import chat_execution_runtime, connector_egress_policy, dataset_precheck_scan_runner
from app.services.document_access_service import _document_acl_owner_allowed


def test_nullable_owner_does_not_match_an_empty_account_identifier():
    assert not _document_acl_owner_allowed(
        account_id="", document=SimpleNamespace(owner_id=None), dataset=SimpleNamespace(owner_id=None)
    )


@pytest.mark.parametrize("config,error", [({}, KeyError), (SimpleNamespace(), AttributeError)])
def test_connector_config_requires_a_host_before_network_resolution(config, error, monkeypatch):
    def resolve(*args, **kwargs):
        pytest.fail("Missing required host must fail before DNS")

    monkeypatch.setattr(connector_egress_policy.socket, "getaddrinfo", resolve)
    with pytest.raises(error):
        connector_egress_policy.validate_db_connector_config(config)


def test_precheck_sampling_requires_the_file_identity_written_in_the_artifact():
    with pytest.raises(KeyError, match="file_size"):
        dataset_precheck_scan_runner._stable_sample_key(
            {"name": "empty.txt", "file_type": "txt", "file_mtime": 0}, salt="type:txt"
        )


def test_source_enrichment_does_not_hide_a_missing_required_document_filename(monkeypatch):
    monkeypatch.setattr(chat_execution_runtime, "maybe_build_source_identification_answer", lambda **kwargs: "source")

    class Query:
        def filter(self, *args):
            return self

        def first(self):
            return SimpleNamespace(doc_metadata={})

        def scalar(self):
            return None

    db = SimpleNamespace(query=lambda *args: Query())
    with pytest.raises(AttributeError, match="filename"):
        chat_execution_runtime._source_identification_answer_from_citations(
            db=db, tenant_id=uuid4(), question="Which document?", citations=[{"document_id": str(uuid4())}]
        )
