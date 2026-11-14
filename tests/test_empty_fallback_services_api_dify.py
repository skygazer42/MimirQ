import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1 import integrations_dify
from app.rag.retrieval.planner import DatasetScopePlan
from app.services.dify_integration import response_cache
from app.types.dify_integration import DifyActor, DifyRetrievalSetting


def test_dify_api_error_keeps_a_real_zero_detail():
    response = integrations_dify._dify_error_response(HTTPException(status_code=400, detail=0))
    assert json.loads(response.body)["error_msg"] == "0"


def test_dify_api_policy_slot_preserves_zero_metadata():
    assert integrations_dify._policy_slot_canonical_terms_by_value(
        [{"value": 0, "terms": ["zero"]}]
    ) == {"0": ["zero"]}


def test_dify_api_answer_record_requires_produced_content():
    with pytest.raises(KeyError, match="content"):
        integrations_dify._record_content_is_answerful({"title": "source", "metadata": {}})


@pytest.mark.parametrize("build_key", [integrations_dify._build_dify_response_cache_key, response_cache._build_dify_response_cache_key])
def test_dify_response_cache_distinguishes_an_unset_model_from_an_explicit_empty_model(build_key, monkeypatch):
    dataset_id = uuid4()
    options = dict(
        actor=DifyActor(tenant_id=uuid4(), account_id="reader"), knowledge_id="knowledge", query="question",
        retrieval_setting=DifyRetrievalSetting(), metadata_condition=None,
        scope_plan=DatasetScopePlan(
            dataset_ids=(dataset_id,), primary_dataset_ids=(dataset_id,), expansion_dataset_ids=(),
            base_dataset_ids=(dataset_id,), matched_dataset_ids=(), matched_terms=(), strict_scope=False,
            route_count=0, matched_route_count=0, included_hint_dataset_count=0,
        ),
        top_k=2, candidate_top_k=4, score_threshold=0.0, policy_plugin_refs=(), corpus_token="corpus",
    )
    monkeypatch.setattr(integrations_dify.settings, "RERANKER_MODEL", None)
    unset_key = build_key(**options)
    monkeypatch.setattr(integrations_dify.settings, "RERANKER_MODEL", "")
    assert build_key(**options) != unset_key
