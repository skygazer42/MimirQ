import pytest

from app.rag.pipeline_plugins.golden_drafts import _format_question


@pytest.mark.parametrize("value,text", [(0, "0"), (False, "False")])
def test_golden_question_keeps_usable_falsy_metadata(value, text) -> None:
    assert _format_question("Value: {value}", {"value": value}) == f"Value: {text}"
