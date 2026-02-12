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
