import logging

import pytest

from app.services import document_qa_service


def test_generate_pairs_llm_failure_falls_back_and_logs(caplog, monkeypatch):
    caplog.set_level(logging.WARNING)

    monkeypatch.setattr(document_qa_service, "_llm_enabled", lambda: True, raising=True)

    def _boom(*args, **kwargs):  # noqa: ANN001,ANN002,ANN003
        raise RuntimeError("LLM down")

    monkeypatch.setattr(document_qa_service, "generate_qa_pairs_with_llm", _boom, raising=True)
    monkeypatch.setattr(
        document_qa_service,
        "extract_qa_pairs_from_text",
        lambda *_args, **_kwargs: [document_qa_service.QAPair(question="q", answer="a")],
        raising=True,
    )

    mode, pairs = document_qa_service._generate_pairs("hello", num_pairs=1, prefer_llm=True)
    assert mode == "extract"
    assert pairs and pairs[0].question == "q"
    assert any("feature=qa_llm_generation" in r.message for r in caplog.records)


def test_generate_pairs_prefer_llm_false_never_calls_llm(monkeypatch):
    monkeypatch.setattr(document_qa_service, "_llm_enabled", lambda: True, raising=True)
    monkeypatch.setattr(
        document_qa_service,
        "generate_qa_pairs_with_llm",
        lambda *_args, **_kwargs: pytest.fail("LLM should not be called when prefer_llm=False"),
        raising=True,
    )
    monkeypatch.setattr(
        document_qa_service,
        "extract_qa_pairs_from_text",
        lambda *_args, **_kwargs: [document_qa_service.QAPair(question="q", answer="a")],
        raising=True,
    )

    mode, pairs = document_qa_service._generate_pairs("hello", num_pairs=1, prefer_llm=False)
    assert mode == "extract"
    assert pairs and pairs[0].answer == "a"


def test_generate_pairs_llm_success_returns_llm_mode(monkeypatch):
    monkeypatch.setattr(document_qa_service, "_llm_enabled", lambda: True, raising=True)
    monkeypatch.setattr(
        document_qa_service,
        "generate_qa_pairs_with_llm",
        lambda *_args, **_kwargs: [document_qa_service.QAPair(question="q", answer="a")],
        raising=True,
    )
    monkeypatch.setattr(
        document_qa_service,
        "extract_qa_pairs_from_text",
        lambda *_args, **_kwargs: pytest.fail("extract should not be called when llm returns pairs"),
        raising=True,
    )

    mode, pairs = document_qa_service._generate_pairs("hello", num_pairs=1, prefer_llm=True)
    assert mode == "llm"
    assert pairs and pairs[0].question == "q"

