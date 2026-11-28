import pytest
from fastapi import HTTPException

from app.api.utils.document_pipeline_input import parse_pipeline_json


def test_parse_pipeline_json_rejects_unknown_fields_with_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        parse_pipeline_json('{"chunk_size": 512, "unexpected_field": true}')

    assert exc_info.value.status_code == 400
