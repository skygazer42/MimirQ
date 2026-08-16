import pytest
from fastapi import HTTPException

from app.api.v1 import documents as documents_module


def test_parse_pipeline_json_rejects_unknown_fields_with_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        documents_module._parse_pipeline_json('{"chunk_size": 512, "unexpected_field": true}')

    assert exc_info.value.status_code == 400
