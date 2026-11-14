from uuid import uuid4

import pytest

from app.api.schemas.regression import ReferenceSource
from app.core.regex_safety import RegexRulesValidationError, validate_regex_rules


@pytest.mark.parametrize("value", [0, False, [], {}])
def test_regex_replacement_does_not_turn_wrong_types_into_delete_instructions(value) -> None:
    with pytest.raises(RegexRulesValidationError):
        validate_regex_rules([{"pattern": "text", "repl": value}])


def test_regex_replacement_can_be_genuinely_omitted() -> None:
    assert validate_regex_rules([{"pattern": "text"}])[0]["repl"] == ""


@pytest.mark.parametrize("value", [0, False, [], {}])
def test_semantic_source_keys_expose_non_string_inputs(value) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReferenceSource(document_id=uuid4(), chunk_id=uuid4(), semantic_keys=[value])


def test_semantic_source_keys_keep_blank_and_missing_collection_contracts() -> None:
    source = ReferenceSource(document_id=uuid4(), chunk_id=uuid4(), semantic_keys=["", " key ", "key"])
    assert source.semantic_keys == ["key"]
