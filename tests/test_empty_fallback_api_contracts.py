from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1 import evaluations, pipeline
from app.api.v1.pipeline_support import auto_annotations, governance_profiles


def test_document_question_response_requires_generated_source_id() -> None:
    question = SimpleNamespace(question="question", expected_answer="answer", context="context", metadata={})
    with pytest.raises(KeyError, match="source_id"):
        evaluations._document_questions_response([question])


def test_parsed_content_projection_preserves_the_database_values() -> None:
    document_id = uuid4()
    query = SimpleNamespace()
    query.filter = lambda *_args: query
    query.all = lambda: [(document_id, None, False)]
    db = SimpleNamespace(query=lambda *_args: query)
    assert auto_annotations._parsed_content_by_doc_id(db, uuid4(), [document_id]) == {document_id: (None, False)}


def test_span_projection_does_not_discard_invalid_required_text() -> None:
    with pytest.raises(AttributeError):
        auto_annotations._normalize_span_annotations("text", [SimpleNamespace(text=None)], max_items=1)


def test_plugin_marker_refs_requires_the_descriptor_fields() -> None:
    with pytest.raises(AttributeError):
        pipeline._plugin_marker_refs("plugin:example@1", SimpleNamespace())


@pytest.mark.parametrize("name", [1, [], {"name": "profile"}])
def test_governance_import_validates_name_instead_of_stringifying(name: object) -> None:
    with pytest.raises(HTTPException) as error:
        governance_profiles._normalize_governance_profile_import_record({"name": name, "payload": {}})
    assert error.value.status_code == 400
    assert "name" in error.value.detail.lower()


@pytest.mark.parametrize("description", [0, False, []])
def test_governance_import_validates_optional_description(description: object) -> None:
    with pytest.raises(HTTPException) as error:
        governance_profiles._normalize_governance_profile_import_record(
            {"name": "profile", "description": description, "payload": {}}
        )
    assert error.value.status_code == 400
    assert "description" in error.value.detail.lower()
