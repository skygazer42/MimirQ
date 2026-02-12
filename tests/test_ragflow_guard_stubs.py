def test_ragflow_pdf_parser_remove_tag_is_static():
    from app.deepdoc.parser.pdf_parser import RAGFlowPdfParser

    assert RAGFlowPdfParser.remove_tag("@@1\t0\t0\t0\t0##hello") == "hello"
    assert RAGFlowPdfParser.remove_tag("") == ""


def test_ragflow_by_plaintext_falls_back_when_llmbundle_unavailable(monkeypatch):
    import app.third_party.ragflow.chunkers.naive as naive_mod

    class _DummyPlainParser:
        def __call__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return [("hello", "")], []

    def _raise(*_args, **_kwargs):  # noqa: ANN001
        raise NotImplementedError("LLMBundle stub")

    monkeypatch.setattr(naive_mod, "PlainParser", _DummyPlainParser, raising=True)
    monkeypatch.setattr(naive_mod, "LLMBundle", _raise, raising=True)

    callback_calls = []

    def _cb(prog, msg=""):  # noqa: ANN001
        callback_calls.append((prog, msg))

    sections, tables, parser = naive_mod.by_plaintext(
        "dummy.pdf",
        binary=b"not-a-real-pdf",
        callback=_cb,
        tenant_id="t",
        layout_recognizer="Some Vision Model",
        lang="Chinese",
    )

    assert sections == [("hello", "")]
    assert tables == []
    assert isinstance(parser, _DummyPlainParser)
    assert any(prog == -1 for (prog, _msg) in callback_calls)


def test_ragflow_llmbundle_disabled_raises(monkeypatch):
    from app.core.config import settings
    from app.third_party.ragflow.common.constants import LLMType
    from app.third_party.ragflow.stubs.llm_service import LLMBundle

    monkeypatch.setattr(settings, "RAGFLOW_VISION_ENABLED", False, raising=False)

    try:
        LLMBundle("t", LLMType.IMAGE2TEXT)
    except NotImplementedError as exc:
        assert "RAGFLOW_VISION_ENABLED" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected NotImplementedError when RAGFLOW_VISION_ENABLED=false")


def test_ragflow_llmbundle_configured_calls_openai_compatible(monkeypatch):
    from app.core.config import settings
    from app.third_party.ragflow.common.constants import LLMType
    import app.third_party.ragflow.stubs.llm_service as llm_mod

    monkeypatch.setattr(settings, "RAGFLOW_VISION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAGFLOW_VISION_API_KEY", "k-test", raising=False)
    monkeypatch.setattr(settings, "RAGFLOW_VISION_API_BASE", "https://example.com/v1", raising=False)
    monkeypatch.setattr(settings, "RAGFLOW_VISION_MODEL", "gpt-4o-mini", raising=False)
    monkeypatch.setattr(settings, "RAGFLOW_VISION_TIMEOUT_SEC", 12, raising=False)
    monkeypatch.setattr(settings, "RAGFLOW_VISION_MAX_TOKENS", 1234, raising=False)
    monkeypatch.setattr(settings, "RAGFLOW_VISION_TEMPERATURE", 0.0, raising=False)

    calls = []

    class _Resp:
        status_code = 200
        text = ""

        def json(self):  # noqa: ANN001
            return {"choices": [{"message": {"content": "OK"}}]}

    class _Session:
        def post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001
            calls.append((url, headers, json, timeout))
            return _Resp()

    monkeypatch.setattr(llm_mod.requests, "Session", lambda: _Session(), raising=True)

    bundle = llm_mod.LLMBundle("t", LLMType.IMAGE2TEXT)
    out = bundle.describe_with_prompt(b"\xff\xd8\xff\x00", prompt="hello")
    assert out == "OK"

    assert calls, "Expected HTTP call"
    url, headers, payload, timeout = calls[0]
    assert url == "https://example.com/v1/chat/completions"
    assert "Authorization" in (headers or {})
    assert headers["Authorization"].startswith("Bearer ")
    assert payload["model"] == "gpt-4o-mini"
    assert payload["max_tokens"] == 1234
    assert payload["temperature"] == 0.0
    assert timeout == 12.0

    msg = payload["messages"][0]
    assert msg["role"] == "user"
    content = msg["content"]
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "hello"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
