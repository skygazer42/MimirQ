from __future__ import annotations

from collections.abc import Awaitable
from types import SimpleNamespace
from uuid import uuid4

from app.rag.evaluation.test_generator import (
    _build_testgen_http_clients,
    _build_testgen_prompt_inputs,
    _normalize_testgen_result_rows,
)


class _ClosedAwaitable(Awaitable[None]):
    def __await__(self):  # noqa: ANN204
        if False:
            yield None
        return None


def test_normalize_question_types_dedupes_and_maps_reasoning() -> None:
    from app.rag.evaluation.test_generator import _normalize_question_types

    assert _normalize_question_types([" factual ", "reasoning", "factual", "unknown"]) == [
        "factual",
        "multi_hop",
    ]


def test_build_testgen_http_clients_disables_trust_env_for_socks_proxy(monkeypatch) -> None:
    import app.rag.evaluation.test_generator as mod

    sync_kwargs = {}
    async_kwargs = {}

    class _FakeSyncClient:
        def __init__(self, **kwargs):  # noqa: ANN003
            sync_kwargs.update(kwargs)

        def close(self) -> None:
            return None

    class _FakeAsyncClient:
        def __init__(self, **kwargs):  # noqa: ANN003
            async_kwargs.update(kwargs)

        def aclose(self) -> _ClosedAwaitable:
            return _ClosedAwaitable()

    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:35983/")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:35983")
    monkeypatch.setattr(mod.httpx, "Client", _FakeSyncClient, raising=True)
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient, raising=True)

    _build_testgen_http_clients()

    assert sync_kwargs["trust_env"] is False
    assert async_kwargs["trust_env"] is False
    assert "proxy" not in sync_kwargs
    assert "proxy" not in async_kwargs


def test_build_testgen_prompt_inputs_supports_builtin_testset_variables() -> None:
    payload = _build_testgen_prompt_inputs(
        chunk_text="Chunk body for prompt selection.",
        num_questions=3,
        normalized_types=["factual", "multi_hop"],
        existing_questions=["Q1", "Q2"],
        prompt_variables=["document_chunk", "n", "existing_questions"],
    )

    assert payload == {
        "document_chunk": "Chunk body for prompt selection.",
        "n": 3,
        "existing_questions": "Q1\nQ2",
    }


def test_build_testgen_prompt_inputs_preserves_legacy_prompt_shape() -> None:
    payload = _build_testgen_prompt_inputs(
        chunk_text="Legacy chunk body.",
        num_questions=2,
        normalized_types=["comparison", "conditional"],
        existing_questions=[],
        prompt_variables=["text", "num_questions", "question_types"],
    )

    assert payload == {
        "text": "Legacy chunk body.",
        "num_questions": 2,
        "question_types": "comparison, conditional",
    }


def test_normalize_testgen_result_rows_accepts_builtin_qa_pairs_shape() -> None:
    rows = _normalize_testgen_result_rows(
        {
            "qa_pairs": [
                {
                    "question": "What color is the flag?",
                    "ground_truth": "The flag is blue.",
                    "difficulty": "reasoning",
                    "evidence_quotes": ["blue flag"],
                    "expected_chunks": ["alpha"],
                }
            ]
        }
    )

    assert rows == [
        {
            "question": "What color is the flag?",
            "expected_answer": "The flag is blue.",
            "question_type": "reasoning",
            "expected_refusal": False,
            "evidence_quotes": ["blue flag"],
            "expected_chunks": ["alpha"],
        }
    ]


def test_generate_questions_from_documents_uses_prompt_selection_and_normalized_rows(monkeypatch) -> None:
    import app.rag.evaluation.test_generator as mod

    doc_id = uuid4()
    chunk_id = uuid4()
    chunk = SimpleNamespace(
        id=chunk_id,
        document_id=doc_id,
        content="Chunk body for generation.",
    )

    monkeypatch.setattr(mod, "filter_allowed_document_ids", lambda *_args, **_kwargs: [doc_id], raising=True)
    monkeypatch.setattr(mod, "_sample_diverse_chunks", lambda chunks, _n: list(chunks), raising=True)
    monkeypatch.setattr(mod.settings, "LLM_TIMEOUT", 30, raising=False)
    monkeypatch.setattr(mod.settings, "LLM_MODEL", "mock-model", raising=False)
    monkeypatch.setattr(mod.settings, "LLM_API_KEY", "mock-key", raising=False)
    monkeypatch.setattr(mod.settings, "LLM_API_BASE", "https://example.test/v1", raising=False)

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def all(self):
            return self._rows

    class _FakeDB:
        def query(self, _model):  # noqa: ANN001
            return _FakeQuery([chunk])

    class _FakePrompt:
        def __init__(self, **kwargs):  # noqa: ANN003
            self.kwargs = kwargs

        def __or__(self, _other):
            return self

        def invoke(self, _inputs):
            return {
                "questions": [
                    {
                        "question": "What is in the chunk?",
                        "expected_answer": "Chunk body for generation.",
                        "question_type": "reasoning",
                    }
                ]
            }

    monkeypatch.setattr(mod, "PromptTemplate", _FakePrompt, raising=True)
    monkeypatch.setattr(mod, "ChatOpenAI", lambda **_kwargs: object(), raising=True)
    monkeypatch.setattr(mod, "JsonOutputParser", lambda: object(), raising=True)
    monkeypatch.setattr(
        mod,
        "resolve_prompt_template",
        lambda **_kwargs: SimpleNamespace(
            id="tpl-1",
            template_key="kg-testgen",
            ab_experiment_key="exp-1",
            ab_variant="A",
            content="Prompt: {text}",
            variables=["text", "num_questions", "question_types"],
        ),
        raising=True,
    )

    rows = mod.generate_questions_from_documents(
        db=_FakeDB(),
        tenant_id=uuid4(),
        account_id="acct",
        document_ids=[doc_id],
        num_questions=1,
        question_types=["reasoning"],
        prompt_template_key="kg-testgen",
    )

    assert len(rows) == 1
    assert rows[0].question == "What is in the chunk?"
    assert rows[0].metadata["question_type"] == "multi_hop"
    assert rows[0].metadata["prompt_template_key"] == "kg-testgen"
