import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest


class _PromptTemplateQuery:
    def __init__(self, *, first_result=None, all_results=None) -> None:  # noqa: ANN001
        self._first_result = first_result
        self._all_results = list(all_results or [])

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def first(self):  # noqa: ANN201
        return self._first_result

    def all(self):  # noqa: ANN201
        return list(self._all_results)


class _PromptTemplateDB:
    def __init__(self, query: _PromptTemplateQuery) -> None:
        self._query = query

    def query(self, _model):  # noqa: ANN001, ANN201
        return self._query


def test_apply_chat_runtime_metrics_context_preserves_existing_values_and_gates_optional_meta() -> None:
    from app.services.chat.response_formatting import apply_chat_runtime_metrics_context

    dataset_id = uuid.uuid4()
    prompt_id = uuid.uuid4()
    metrics = {
        "dataset_id": "existing-dataset",
        "prompt_template_id": "existing-template",
        "tenant_qps_quota": {"enabled": False},
    }

    result = apply_chat_runtime_metrics_context(
        metrics,
        dataset_id_used=dataset_id,
        effective_prompt_template_id=prompt_id,
        effective_prompt_template_key="kb_assistant",
        effective_prompt_ab_experiment_key="exp-a",
        dataset_rag_defaults_applied_fields=["top_k"],
        dataset_rag_config_template_defaults_applied_fields=["temperature"],
        rag_config_template_meta={"template": "balanced"},
        dataset_prompt_defaults_applied_fields=["system_prompt"],
        tenant_qps_meta={"enabled": True, "scope": "chat"},
        quota_meta={"enabled": False, "scope": "tenant_documents"},
    )

    assert result["dataset_id"] == "existing-dataset"
    assert result["prompt_template_id"] == "existing-template"
    assert result["prompt_template_key"] == "kb_assistant"
    assert result["prompt_ab_experiment_key"] == "exp-a"
    assert result["dataset_rag_defaults_applied"] is True
    assert result["dataset_rag_defaults_fields"] == ["top_k"]
    assert result["dataset_rag_config_template_defaults_applied"] is True
    assert result["dataset_rag_config_template_defaults_fields"] == ["temperature"]
    assert result["rag_config_template"] == {"template": "balanced"}
    assert result["dataset_prompt_defaults_applied"] is True
    assert result["dataset_prompt_defaults_fields"] == ["system_prompt"]
    assert result["tenant_qps_quota"] == {"enabled": False}
    assert "quota" not in result


def test_compute_chunk_coverage_metrics_from_ranges_clips_gaps_and_overlap() -> None:
    from app.services.chunking.statistics import compute_chunk_coverage_metrics_from_ranges

    result = compute_chunk_coverage_metrics_from_ranges(
        [(-3, 4), (2, 6), (8, 12), (9, 9)],
        total_characters=10,
    )

    assert result == {
        "sum_chunk_chars": 10,
        "covered_chars": 8,
        "coverage_ratio": 0.8,
        "overlap_waste_ratio": 0.2,
        "gap_count": 1,
        "largest_gap": 2,
    }


def test_validate_and_normalize_fls_policy_normalizes_entries_and_trims_duplicates() -> None:
    from app.api.schemas.identity.field_access import FlsPolicy
    from app.services.tables.field_security import validate_and_normalize_fls_policy

    policy = FlsPolicy(
        version="1",
        rules=[
            {
                "id": "Rule-1",
                "name": "  Sensitive Email  ",
                "enabled": True,
                "sources": ["db_catalog", " DB_CATALOG ", "table_store"],
                "column_name_regex": "email",
                "allow_roles": ["Admin", " admin ", "", "auditor"],
                "allow_account_ids": ["acct-1", "acct-1", "acct-2"],
                "mask": "  [MASKED]  ",
            }
        ],
    )

    normalized = validate_and_normalize_fls_policy(policy)

    assert normalized.version == "1"
    assert len(normalized.rules) == 1
    rule = normalized.rules[0]
    assert rule.id == "Rule-1"
    assert rule.name == "Sensitive Email"
    assert rule.sources == ["db_catalog", "table_store"]
    assert rule.allow_roles == ["admin", "auditor"]
    assert rule.allow_account_ids == ["acct-1", "acct-2"]
    assert rule.mask == "[MASKED]"


def test_resolve_prompt_template_uses_uniform_weights_when_all_variant_weights_are_nonpositive() -> None:
    from app.services.prompts.resolver import resolve_prompt_template

    tenant_id = uuid.uuid4()
    variants = [
        SimpleNamespace(ab_weight=-2.0, ab_variant="A", updated_at=datetime(2026, 8, 1, tzinfo=UTC)),
        SimpleNamespace(ab_weight=0.0, ab_variant="B", updated_at=datetime(2026, 8, 2, tzinfo=UTC)),
    ]
    db = _PromptTemplateDB(_PromptTemplateQuery(all_results=variants))

    resolved = resolve_prompt_template(
        db=db,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        ab_experiment_key="exp-1",
        ab_user_key="user-7",
    )

    assert resolved is variants[1]


def test_merge_rag_config_with_dataset_defaults_applies_only_missing_fields() -> None:
    from app.api.schemas.conversations.chat import ChatRAGConfig
    from app.services.retrieval.defaults import merge_rag_config_with_dataset_defaults

    rag_config = ChatRAGConfig(top_k=12, visible_evidence_only=False)

    merged, applied = merge_rag_config_with_dataset_defaults(
        rag_config=rag_config,
        request_fields_set={"top_k", "visible_evidence_only"},
        raw_dataset_defaults={
            "top_k": 7,
            "retrieval_contract_mode": "evidence_strict",
            "enable_reranker": False,
        },
    )

    assert merged.top_k == 12
    assert merged.visible_evidence_only is False
    assert merged.retrieval_contract_mode == "evidence_strict"
    assert merged.enable_reranker is False
    assert applied == ["retrieval_contract_mode", "enable_reranker"]


def test_compare_regression_items_builds_significance_and_case_labels() -> None:
    from app.models.evaluation.results import RagasRegressionItem
    from app.services.evaluation.run_significance import compare_regression_items

    first_case, second_case = uuid.UUID(int=1), uuid.UUID(int=2)
    base_items = [
        RagasRegressionItem(case_id=second_case, question="Second", scores={"faithfulness": 0.2, "binary": 0.0}),
        RagasRegressionItem(case_id=first_case, question="First", scores={"faithfulness": 0.1, "binary": 0.0}),
    ]
    target_items = [
        RagasRegressionItem(case_id=first_case, question="First+", scores={"faithfulness": 0.3, "binary": 1.0}),
        RagasRegressionItem(case_id=second_case, question="Second+", scores={"faithfulness": 0.21, "binary": 0.0}),
    ]

    result = compare_regression_items(
        base_items=base_items,
        target_items=target_items,
        metric_keys=["faithfulness", "binary"],
        bootstrap_iterations=50,
        max_case_diffs=10,
    )

    assert result["summary"] == {"paired_cases": 2, "metrics_compared": 2, "bh_corrected": True}
    assert [row["key"] for row in result["significance"]] == ["faithfulness", "binary"]
    assert result["significance"][1]["mcnemar_p_value"] == 1.0
    assert result["case_diffs"][0]["case_id"] == str(first_case)
    assert result["case_diffs"][0]["question"] == "First+"
    assert result["case_diffs"][0]["label"] == "改善"
    assert result["case_diffs"][1]["label"] == "无明显变化"


@pytest.mark.asyncio
async def test_prom_query_sums_multiple_series_and_ignores_malformed_values() -> None:
    from app.services.observability.slo import _prom_query

    request_log: list[tuple[str, dict[str, str]]] = []
    payload = {
        "status": "success",
        "data": {
            "result": [
                {"value": [1723872000, "1.5"]},
                {"value": [1723872001, "2.25"]},
                {"value": [1723872002, "bad"]},
                {"missing": "value"},
            ]
        },
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        request_log.append((str(request.url), dict(request.url.params)))
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await _prom_query(client, base_url="https://metrics.example", promql="sum(metric)")

    assert result == 3.75
    assert request_log == [("https://metrics.example/api/v1/query?query=sum%28metric%29", {"query": "sum(metric)"})]
