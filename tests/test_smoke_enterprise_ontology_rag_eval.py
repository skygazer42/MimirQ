from uuid import uuid4

from app.api.schemas.conversations import ChatResponse, Citation
from scripts.smoke_enterprise_ontology_rag_eval import CASES, score_turn, summarize


def test_citation_recall_requires_the_labeled_page_and_fact():
    case = CASES["two_hop"]
    documents = {name: uuid4() for name in ("work_order", "installation", "same_name")}
    response = ChatResponse(
        conversation_id=uuid4(),
        assistant_message_id=uuid4(),
        request_id="test",
        content="工单 WO-01 对应设备 E-102，安装在 LINE-A。",
        citations=[
            Citation(
                document_id=documents["work_order"],
                document_name="维修工单.pdf",
                chunk_id=uuid4(),
                chunk_content="维修工单 WO-01 归属于设备 E-102。",
                page_number=1,
            ),
            Citation(
                document_id=documents["installation"],
                document_name="安装台账.pdf",
                chunk_id=uuid4(),
                chunk_content="设备 E-102 安装在产线 LINE-B。",
                page_number=1,
            ),
        ],
    )

    score = score_turn(case, response, documents)

    assert score.answer_correct
    assert score.matched_facts == ("work_order",)
    assert score.unexpected_citations == ("installation",)
    assert summarize([score])["citation_recall"] == {"hits": 1, "total": 2}
    response.citations[1].chunk_content = "设备 E-102 安装在产线 LINE-AB。"
    assert score_turn(case, response, documents).matched_facts == ("work_order",)
    response.citations[1].chunk_content = "设备 E-102 安装在产线 LINE-A。"
    response.citations[1].page_number = 2
    assert score_turn(case, response, documents).matched_facts == ("work_order",)


def test_no_evidence_requires_a_refusal_without_an_asserted_line_or_citation():
    case = CASES["restricted"]
    response = ChatResponse(
        conversation_id=uuid4(),
        assistant_message_id=uuid4(),
        request_id="test",
        content="未找到两跳均有原文依据的关系路径。",
    )
    assert score_turn(case, response, {}).answer_correct

    response.content = "没有足够信息，但是设备可能在 LINE-Z。"
    score = score_turn(case, response, {})
    assert not score.answer_correct
    assert score.no_evidence_false_positive

    response.content = "未找到两跳均有原文依据的关系路径。"
    response.citations = [
        Citation(
            document_id=uuid4(), document_name="未授权台账.pdf", chunk_id=uuid4(), chunk_content="LINE-A", page_number=1
        )
    ]
    assert score_turn(case, response, {}).no_evidence_false_positive


def test_ontology_gate_requires_the_requested_path_even_for_an_unavailable_answer():
    case = CASES["restricted"]
    unavailable = "未找到两跳均有原文依据的关系路径。"
    plan = {"object_type": "work_order", "business_key": "WO-01", "relation_path": list(case.relations)}
    response = ChatResponse(
        conversation_id=uuid4(),
        assistant_message_id=uuid4(),
        request_id="test",
        content=unavailable,
        metrics={"route": "standard", "ontology_used": True, "ontology_fusion": {"plan": plan}},
    )

    assert score_turn(case, response, {}).ontology_passed
    plan["relation_path"].reverse()
    assert not score_turn(case, response, {}).ontology_passed
