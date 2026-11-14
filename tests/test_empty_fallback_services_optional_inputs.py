from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import chat_bootstrap_runtime, chat_conversation_titles, chat_execution_runtime, chunk_preset_service, config_hot_reload


class PresetQuery:
    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def limit(self, value):
        return self

    def all(self):
        return []


def resolve_template(**selectors):
    return chat_bootstrap_runtime._resolve_rag_template_runtime(
        db=object(), tenant_id=uuid4(), account_id="reader", request_id="request",
        effective_rag_config=SimpleNamespace(), rag_fields_set=set(), effective_rag_config_template_id=None,
        effective_rag_config_template_key=selectors.get("key"),
        effective_rag_config_ab_experiment_key=selectors.get("experiment"),
    )


def list_presets(q):
    return chunk_preset_service.list_chunk_presets(
        db=SimpleNamespace(query=lambda model: PresetQuery()), tenant_id=uuid4(), q=q,
        limit=10, dataset_id=None, include_global=True,
    )


def should_reload(previous):
    state = config_hot_reload.ConfigHotReloadState(
        schema="test", ops_fingerprint="ops", retrieval_fingerprint="retrieval", combined_fingerprint="current"
    )
    return config_hot_reload.should_hot_reload_config(previous_combined_fingerprint=previous, current_state=state)


def extractive_answer(override):
    return chat_execution_runtime.build_extractive_fallback_answer(
        question="What is the evidence?", citations=[{"document_name": "Guide", "chunk_content": "Valid evidence text."}],
        direct_answer_override=override,
    )


@pytest.mark.parametrize("value", [0, False])
@pytest.mark.parametrize("consume", [
    lambda value: resolve_template(key=value),
    lambda value: resolve_template(experiment=value),
    list_presets,
    chat_conversation_titles.derive_auto_conversation_title,
    should_reload,
    extractive_answer,
])
def test_supplied_optional_string_is_not_silently_treated_as_omitted(consume, value):
    with pytest.raises(AttributeError):
        consume(value)


def test_real_missing_optional_inputs_keep_their_existing_meaning():
    assert resolve_template()[1] is None
    assert list_presets(None) == []
    assert chat_conversation_titles.derive_auto_conversation_title(None) is None
    assert should_reload(None) is True
    assert "Valid evidence text." in extractive_answer(None)
