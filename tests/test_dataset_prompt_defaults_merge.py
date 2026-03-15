from __future__ import annotations

import uuid

from app.services.prompt_defaults import merge_prompt_defaults_with_dataset


def test_prompt_defaults_prefer_id_over_key():  # noqa: ANN001
    ds_meta = {
        "default_prompt_template_id": str(uuid.uuid4()),
        "default_prompt_template_key": "my_template",
        "default_prompt_ab_experiment_key": "exp-1",
    }
    pid, key, ab, applied = merge_prompt_defaults_with_dataset(
        prompt_template_id=None,
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
        request_fields_set=set(),
        dataset_meta=ds_meta,
    )
    assert pid is not None
    assert key is None  # key not applied because id won
    assert ab == "exp-1"
    assert set(applied) == {"prompt_template_id", "prompt_ab_experiment_key"}


def test_prompt_defaults_respects_explicit_null():  # noqa: ANN001
    ds_meta = {"default_prompt_template_id": str(uuid.uuid4())}
    pid, _key, _ab, applied = merge_prompt_defaults_with_dataset(
        prompt_template_id=None,  # explicit null in request
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
        request_fields_set={"prompt_template_id"},
        dataset_meta=ds_meta,
    )
    assert pid is None
    assert applied == []


def test_prompt_defaults_apply_key_when_no_id_default():  # noqa: ANN001
    ds_meta = {"default_prompt_template_key": "kb_assistant"}
    pid, key, _ab, applied = merge_prompt_defaults_with_dataset(
        prompt_template_id=None,
        prompt_template_key="",
        prompt_ab_experiment_key=None,
        request_fields_set=set(),
        dataset_meta=ds_meta,
    )
    assert pid is None
    assert key == "kb_assistant"
    assert set(applied) == {"prompt_template_key"}

