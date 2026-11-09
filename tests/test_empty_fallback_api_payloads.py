import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.v1 import document_chunk_preview, document_preview, retrieval_explain
from app.core.logging_config import JSONFormatter, bind_request_context, reset_request_context


@pytest.mark.parametrize("row", [{}, {"page_content": None}, {"page_content": False}])
def test_preview_materializers_do_not_construct_empty_documents_from_invalid_payloads(row) -> None:
    with pytest.raises((KeyError, ValidationError)):
        document_chunk_preview._materialize_preview_documents([row])
    with pytest.raises((KeyError, ValidationError)):
        document_preview._materialize_preview_documents(
            {"documents": [row], "resolved_backend": "text"}, parser_backend="text"
        )


def test_preview_materializers_keep_a_real_empty_document() -> None:
    documents = document_chunk_preview._materialize_preview_documents([{"page_content": "", "metadata": {}}])
    assert documents[0].page_content == ""


def test_history_serializer_exposes_missing_declared_message_fields() -> None:
    with pytest.raises(AttributeError):
        retrieval_explain._as_history_dicts([SimpleNamespace()])


def test_log_projection_does_not_replace_a_supplied_empty_identity_with_context() -> None:
    tokens = bind_request_context(request_id="current-request", tenant_id="current-tenant")
    try:
        record = logging.LogRecord("test", logging.INFO, "", 0, "message", (), None)
        record.request_id = ""
        record.tenant_id = None
        payload = json.loads(JSONFormatter().format(record))
        assert "request_id" not in payload
        assert "tenant_id" not in payload
    finally:
        reset_request_context(tokens)
