import pytest

from app.rag.kg.extraction.backend_router import resolve_extraction_backend
from app.rag.kg.extraction.processor import _collect_event_entities, _render_prompt
from app.rag.kg.extraction_job_options import (
    build_kg_extraction_job_options,
    kg_extraction_job_options_fingerprint,
    normalize_kg_extraction_job_options,
)


def _options(**overrides):
    values = dict(
        pipeline_hash=None,
        prompt_template_id=None,
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
        extraction_backend="llm",
        kg_python_plugin=None,
        kg_python_params={},
        replace_existing=True,
        prune_orphan_entities=True,
        extract_relations=False,
        extract_skills=False,
    )
    values.update(overrides)
    return build_kg_extraction_job_options(**values)


def test_frozen_job_options_keep_the_selected_values_and_fingerprint_them() -> None:
    absent = _options()
    supplied = _options(pipeline_hash="", prompt_template_key=" ", kg_python_plugin="")
    assert supplied["pipeline_hash"] == ""
    assert supplied["prompt_template_key"] == " "
    assert supplied["kg_python_plugin"] == ""
    assert normalize_kg_extraction_job_options(supplied) == supplied
    assert kg_extraction_job_options_fingerprint(supplied) != kg_extraction_job_options_fingerprint(absent)


@pytest.mark.parametrize("field", ["pipeline_hash", "prompt_template_key", "kg_python_plugin"])
@pytest.mark.parametrize("value", [0, False, [], {}])
def test_frozen_job_wire_codec_rejects_wrong_string_types(field, value) -> None:
    payload = _options()
    payload[field] = value
    with pytest.raises(ValueError):
        normalize_kg_extraction_job_options(payload)


@pytest.mark.parametrize("backend", ["", "   ", "unknown-backend"])
def test_explicit_invalid_extraction_backend_is_observable(backend) -> None:
    with pytest.raises(ValueError):
        resolve_extraction_backend(llm_processor=object(), requested_backend=backend)


def test_supplied_empty_prompt_does_not_select_the_builtin_prompt() -> None:
    assert _render_prompt("", context="chunk", schema={}, max_events=2, max_entities=2) == ""


def test_duplicate_entities_merge_the_already_normalized_payload() -> None:
    rows = _collect_event_entities(
        [
            {"name": "Mimir", "type": "organization", "description": "", "role": "", "evidence_quote": ""},
            {
                "name": "Mimir",
                "type": "organization",
                "description": "Longer description",
                "role": " owner ",
                "evidence_quote": " quote ",
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["description"] == "Longer description"
    assert rows[0]["role"] == "owner"
    assert rows[0]["evidence_quote"] == "quote"
