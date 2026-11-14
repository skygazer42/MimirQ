import pytest

from app.api.v1.parsing import _extract_markdown_pair_from_documents
from app.core.token_utils import estimate_tokens


@pytest.mark.parametrize("text", [None, 0, False])
def test_required_parser_text_is_not_replaced_by_an_empty_storage_value(text) -> None:
    with pytest.raises((AttributeError, TypeError)):
        _extract_markdown_pair_from_documents([{"page_content": text, "metadata": {}}])


@pytest.mark.parametrize("text", [None, 0, False])
def test_required_token_input_does_not_fabricate_a_zero_count(text) -> None:
    with pytest.raises((AttributeError, TypeError)):
        estimate_tokens(text)


def test_actual_empty_parser_text_and_token_inputs_remain_valid() -> None:
    assert _extract_markdown_pair_from_documents([{"page_content": "", "metadata": {}}]) == ("", "")
    assert estimate_tokens("") == 0
