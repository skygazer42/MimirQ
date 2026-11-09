import json

import httpx
import pytest
import requests

from app.parsing.parsers.deepseek_ocr_parser import DeepSeekOCRParser
from app.parsing.parsers.mathpix_parser import _call_mathpix_backend_async


@pytest.mark.parametrize("message, error", [({}, KeyError), ({"content": None}, AttributeError), ({"content": 0}, AttributeError), ({"content": False}, AttributeError)])
def test_deepseek_ocr_does_not_invent_text_for_a_malformed_response(monkeypatch, message, error):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SILICONFLOW_API_KEY", "test-key")
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps({"choices": [{"message": message}]}).encode()
    monkeypatch.setattr(requests.Session, "post", lambda *_args, **_kwargs: response)

    with pytest.raises(error):
        DeepSeekOCRParser()._call_api(b"image", mime_type="image/png")


@pytest.mark.parametrize("payload, error", [({}, KeyError), ({"text": None}, AttributeError), ({"text": 0}, AttributeError), ({"text": False}, AttributeError)])
@pytest.mark.asyncio
async def test_mathpix_does_not_invent_text_for_a_malformed_response(monkeypatch, tmp_path, payload, error):
    client_class = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_class(transport=transport, **kwargs))
    file_path = tmp_path / "document.pdf"
    file_path.write_bytes(b"pdf payload")

    with pytest.raises(error):
        await _call_mathpix_backend_async(file_path=file_path, app_id="test-id", app_key="test-key")
