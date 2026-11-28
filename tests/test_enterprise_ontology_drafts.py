from uuid import uuid4

from app.rag.kg.enterprise_ontology.consumption import OntologyAnswer, QuestionPlan
from app.rag.kg.enterprise_ontology.definition import DocumentTemplate
from app.rag.kg.enterprise_ontology.drafts import render_draft


def test_document_template_marks_unverified_required_fields():
    template = DocumentTemplate.model_validate({
        "title": "整改说明",
        "fields": {
            "device": {"label": "设备", "source": "object_key", "required": True},
            "count": {"label": "逾期数量", "source": "metric", "required": True},
        },
    })
    answer = OntologyAnswer(
        ontology_version_id=uuid4(), plan=QuestionPlan(business_key="E-102"), answer="没有数量结果"
    )
    draft = render_draft(template, answer, {})
    assert draft.missing_required == ["device", "count"]
    assert "设备" in draft.markdown and "E-102" not in draft.markdown and "待确认" in draft.markdown
