import json

import pytest
import requests

from app.rag.ingestion.parsing.factory import ParserFactory
from app.rag.ingestion.parsing.parsers.deepseek_ocr_parser import DeepSeekOCRParser


@pytest.mark.parametrize(
    "message, error",
    [
        ({}, KeyError),
        ({"content": None}, AttributeError),
        ({"content": 0}, AttributeError),
        ({"content": False}, AttributeError),
    ],
)
def test_deepseek_ocr_does_not_invent_text_for_a_malformed_response(monkeypatch, message, error):
    from app.infrastructure.config import settings

    monkeypatch.setattr(settings, "SILICONFLOW_API_KEY", "test-key")
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps({"choices": [{"message": message}]}).encode()
    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: response)

    with pytest.raises(error):
        DeepSeekOCRParser()._call_api(b"image", mime_type="image/png")


def test_unregistered_mathpix_backend_is_rejected_before_parsing():
    factory = ParserFactory.__new__(ParserFactory)
    with pytest.raises(ValueError, match="Unsupported parser backend 'mathpix'"):
        factory.resolve_backend(".pdf", "mathpix")
