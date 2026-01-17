from app.rag.kg.extraction.extractor import _is_chunk_unchanged
from app.rag.kg.models import KgSourceEvent


def _event(*, content_hash: str | None, extra: dict | None) -> KgSourceEvent:
    refs = {"content_hash": content_hash} if content_hash is not None else {}
    return KgSourceEvent(
        title="t",
        summary="s",
        content="c",
        references=refs,
        extra_data=extra,
    )


def test_is_chunk_unchanged_requires_hash_and_prompt_selector_match():
    expected = {
        "kg_prompt_template_id": "",
        "kg_prompt_template_key": "",
        "kg_prompt_ab_experiment_key": "",
    }
    extra = {
        "kg_prompt_template_id": "",
        "kg_prompt_template_key": "",
        "kg_prompt_ab_experiment_key": "",
    }
    prior = [_event(content_hash="h1", extra=extra), _event(content_hash="h1", extra=extra)]

    assert _is_chunk_unchanged(prior, content_hash="h1", prompt_selector_expected=expected) is True
    assert _is_chunk_unchanged(prior, content_hash="h2", prompt_selector_expected=expected) is False
    assert _is_chunk_unchanged([_event(content_hash=None, extra=extra)], content_hash="h1", prompt_selector_expected=expected) is False
    assert _is_chunk_unchanged([_event(content_hash="h1", extra=None)], content_hash="h1", prompt_selector_expected=expected) is False


def test_is_chunk_unchanged_fails_when_any_event_has_selector_mismatch():
    expected = {
        "kg_prompt_template_id": "tpl",
        "kg_prompt_template_key": "k",
        "kg_prompt_ab_experiment_key": "ab",
    }
    good = {
        "kg_prompt_template_id": "tpl",
        "kg_prompt_template_key": "k",
        "kg_prompt_ab_experiment_key": "ab",
    }
    bad = {
        "kg_prompt_template_id": "tpl2",
        "kg_prompt_template_key": "k",
        "kg_prompt_ab_experiment_key": "ab",
    }
    prior = [_event(content_hash="h1", extra=good), _event(content_hash="h1", extra=bad)]
    assert _is_chunk_unchanged(prior, content_hash="h1", prompt_selector_expected=expected) is False

