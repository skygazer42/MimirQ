from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.chat import Conversation, Message
from app.models.evidence import EvidenceItem, EvidenceSuite
from app.models.feedback import MessageFeedback


def _load_rollout_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "prepare_ltr_rollout.py"
    spec = importlib.util.spec_from_file_location("prepare_ltr_rollout", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_materialize_feedback_case_infers_question_and_trace() -> None:
    from app.services.ltr_rollout_workflow import materialize_feedback_case

    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    feedback_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    request_id = "req-rollout-1"
    now = datetime.now(timezone.utc)

    conversation = Conversation(
        id=conversation_id,
        tenant_id=tenant_id,
        user_id=None,
        dataset_id=dataset_id,
        title="demo",
        document_ids=[document_id],
        message_count=2,
        created_at=now,
        updated_at=now,
    )
    user_message = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="user",
        content="What is revenue?",
        citations=[],
        message_metadata={},
        created_at=now,
    )
    assistant = Message(
        id=assistant_message_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="assistant",
        content="Revenue is 123.",
        citations=[
            {
                "document_id": str(document_id),
                "chunk_id": str(chunk_id),
                "page_number": 3,
                "chunk_index": 9,
            }
        ],
        message_metadata={"dataset_id": str(dataset_id), "request_id": request_id},
        created_at=now,
    )
    feedback = MessageFeedback(
        id=feedback_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=assistant_message_id,
        account_id="u",
        rating=2,
        reason="bad",
        tags=["neg"],
        expected_answer="Revenue is 120.",
        extra={"source": "test"},
    )

    out = materialize_feedback_case(
        feedback=feedback,
        assistant=assistant,
        conversation=conversation,
        user_message=user_message,
        trace_payload={
            "request_id": request_id,
            "citations_count": 1,
        },
    )

    assert out.dataset_id == str(dataset_id)
    assert out.question == "What is revenue?"
    assert out.expected_answer == "Revenue is 120."
    assert out.reference_sources[0]["document_id"] == str(document_id)
    assert out.reference_sources[0]["chunk_id"] == str(chunk_id)
    assert out.tags == ["neg"]
    assert out.extra["feedback_id"] == str(feedback_id)
    assert out.extra["retrieval_trace_request_id"] == request_id
    assert out.extra["retrieval_trace"]["citations_count"] == 1


def test_build_rollout_regression_bundle_materializes_approved_evidence_and_feedback() -> None:
    from app.services.ltr_rollout_workflow import (
        FeedbackCaseMaterialization,
        build_rollout_regression_bundle,
    )

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    suite = EvidenceSuite(
        id=suite_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        name="gold",
        description=None,
        tags=["eval"],
        config={},
        created_by="u",
        created_at=now,
        updated_at=now,
        archived_at=None,
    )
    approved = EvidenceItem(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        suite_id=suite_id,
        status="approved",
        query="Q1",
        expected_answer="A1",
        tags=["gold"],
        source_metadata={},
        reference_sources=[{"document_id": str(document_id), "chunk_id": str(chunk_id)}],
        retrieval_snapshot={},
        rag_config_snapshot={},
        notes=None,
        regression_case_id=None,
        created_by="u",
        created_at=now,
        updated_at=now,
    )
    reviewed = EvidenceItem(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        suite_id=suite_id,
        status="reviewed",
        query="Q-reviewed",
        expected_answer="A-reviewed",
        tags=[],
        source_metadata={},
        reference_sources=[{"document_id": str(document_id), "chunk_id": str(uuid.uuid4())}],
        retrieval_snapshot={},
        rag_config_snapshot={},
        notes=None,
        regression_case_id=None,
        created_by="u",
        created_at=now,
        updated_at=now,
    )
    feedback_case = FeedbackCaseMaterialization(
        feedback_id=str(uuid.uuid4()),
        dataset_id=str(dataset_id),
        question="Q2",
        expected_answer="A2",
        reference_sources=[{"document_id": str(document_id), "chunk_id": str(uuid.uuid4())}],
        tags=["neg"],
        extra={"rating": 2},
    )

    bundle = build_rollout_regression_bundle(
        dataset_id=dataset_id,
        suite=suite,
        evidence_items=[approved, reviewed],
        feedback_cases=[feedback_case],
        generated_at="2026-03-07T00:00:00Z",
    )

    assert bundle["schema"] == "mimirq.regression_cases.v1"
    assert bundle["dataset_id"] == str(dataset_id)
    assert bundle["source_summary"] == {
        "approved_evidence_items": 1,
        "selected_feedback_cases": 1,
        "total_items": 2,
    }
    assert [item["question"] for item in bundle["items"]] == ["Q1", "Q2"]
    assert bundle["items"][0]["extra"]["source"] == "evidence_suite"
    assert bundle["items"][1]["extra"]["source"] == "feedback"


def test_build_rollout_regression_bundle_rejects_mixed_dataset_ids() -> None:
    from app.services.ltr_rollout_workflow import (
        FeedbackCaseMaterialization,
        build_rollout_regression_bundle,
    )

    dataset_id = uuid.uuid4()
    suite = EvidenceSuite(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dataset_id=dataset_id,
        name="suite",
        description=None,
        tags=[],
        config={},
        created_by="u",
    )
    feedback_case = FeedbackCaseMaterialization(
        feedback_id=str(uuid.uuid4()),
        dataset_id=str(uuid.uuid4()),
        question="Q",
        expected_answer=None,
        reference_sources=[{"document_id": str(uuid.uuid4()), "chunk_id": str(uuid.uuid4())}],
        tags=[],
        extra={},
    )

    with pytest.raises(ValueError, match="dataset_id"):
        build_rollout_regression_bundle(
            dataset_id=dataset_id,
            suite=suite,
            evidence_items=[],
            feedback_cases=[feedback_case],
        )


def test_build_rollout_comparison_prefers_active_ltr_baseline() -> None:
    from app.services.ltr_rollout_workflow import build_rollout_comparison

    comparison = build_rollout_comparison(
        generated_at="2026-03-07T00:00:00Z",
        candidate_eval={
            "schema": "mimirq.ltr_offline_eval.v1",
            "baseline": {"hit": 0.4, "mrr": 0.3, "recall": 0.5, "ndcg": 0.35},
            "ltr": {"hit": 0.7, "mrr": 0.6, "recall": 0.8, "ndcg": 0.65},
            "lineage": {"model_sha256": "c" * 64},
        },
        baseline_eval={
            "schema": "mimirq.ltr_offline_eval.v1",
            "ltr": {"hit": 0.5, "mrr": 0.45, "recall": 0.6, "ndcg": 0.5},
            "lineage": {"model_sha256": "b" * 64},
        },
        active_model_id="baseline-model",
        candidate_model_id="candidate-model",
    )

    assert comparison["schema"] == "mimirq.ltr_rollout_comparison.v1"
    assert comparison["baseline_source"] == "active_ltr_model"
    assert comparison["active_model_id"] == "baseline-model"
    assert comparison["candidate_model_id"] == "candidate-model"
    assert comparison["deltas"] == {
        "hit": 0.2,
        "mrr": 0.15,
        "recall": 0.2,
        "ndcg": 0.15,
    }
    assert comparison["activation"]["performed"] is False
    assert comparison["activation"]["status"] == "manual_review_required"


def test_prepare_ltr_rollout_writes_artifacts_without_activation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.ltr_rollout_workflow import FeedbackCaseMaterialization

    mod = _load_rollout_script()

    dataset_id = uuid.uuid4()
    suite = EvidenceSuite(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dataset_id=dataset_id,
        name="gold",
        description=None,
        tags=[],
        config={},
        created_by="u",
    )
    evidence_item = EvidenceItem(
        id=uuid.uuid4(),
        tenant_id=suite.tenant_id,
        dataset_id=dataset_id,
        suite_id=suite.id,
        status="approved",
        query="Q1",
        expected_answer="A1",
        tags=["gold"],
        source_metadata={},
        reference_sources=[{"document_id": str(uuid.uuid4()), "chunk_id": str(uuid.uuid4())}],
        retrieval_snapshot={},
        rag_config_snapshot={},
        notes=None,
        regression_case_id=None,
        created_by="u",
    )
    feedback_case = FeedbackCaseMaterialization(
        feedback_id=str(uuid.uuid4()),
        dataset_id=str(dataset_id),
        question="Q2",
        expected_answer="A2",
        reference_sources=[{"document_id": str(uuid.uuid4()), "chunk_id": str(uuid.uuid4())}],
        tags=["neg"],
        extra={"rating": 2},
    )

    baseline_model = tmp_path / "baseline-model.json"
    baseline_model.write_text("{\"baseline\":true}\n", encoding="utf-8")
    baseline_manifest = tmp_path / "baseline-manifest.json"
    baseline_manifest.write_text("{\"schema\":\"mimirq.ltr_model_manifest.v1\"}\n", encoding="utf-8")

    def _fake_train(*, cases_path: Path, out_model_path: Path, out_manifest_path: Path, **_kwargs) -> None:
        assert cases_path.exists()
        out_model_path.write_text("{\"candidate\":true}\n", encoding="utf-8")
        out_manifest_path.write_text(
            json.dumps(
                {
                    "schema": "mimirq.ltr_model_manifest.v1",
                    "model_sha256": "a" * 64,
                    "feature_schema": "mimirq.ltr_features.v1",
                    "feature_names": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def _fake_eval(*, model_path: Path, out_json_path: Path, **_kwargs) -> None:
        summary = {
            "schema": "mimirq.ltr_offline_eval.v1",
            "cases_total": 2,
            "cases_used": 2,
            "k": 20,
            "top_k": 50,
            "baseline": {"hit": 0.4, "mrr": 0.3, "recall": 0.5, "ndcg": 0.35},
            "ltr": {"hit": 0.6, "mrr": 0.5, "recall": 0.7, "ndcg": 0.55},
            "lineage": {"model_sha256": ("c" if "candidate" in model_path.name else "b") * 64},
        }
        if "baseline" in model_path.name:
            summary["ltr"] = {"hit": 0.5, "mrr": 0.45, "recall": 0.6, "ndcg": 0.5}
        out_json_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")

    activated: list[str] = []

    monkeypatch.setattr(mod, "_run_train", _fake_train, raising=True)
    monkeypatch.setattr(mod, "_run_eval", _fake_eval, raising=True)
    monkeypatch.setattr(mod, "resolve_active_model_paths", lambda: (str(baseline_model), str(baseline_manifest), 1, "baseline-id"), raising=True)
    monkeypatch.setattr(
        mod,
        "register_model",
        lambda *, model_bytes, _manifest_bytes, _actor_id: type(
            "RegisteredModel",
            (),
            {"model_id": "candidate-id", "model_sha256": "a" * 64, "size_bytes": len(model_bytes), "feature_spec_version": 1},
        )(),
        raising=True,
    )
    monkeypatch.setattr(mod, "activate_model", lambda *_args, **_kwargs: activated.append("activated"), raising=True)

    result = mod.prepare_ltr_rollout(
        workflow_dir=tmp_path / "workflow",
        base_url="http://localhost:8000/api/v1",
        tenant_id=str(uuid.uuid4()),
        user_id="operator",
        suite=suite,
        evidence_items=[evidence_item],
        feedback_cases=[feedback_case],
        register_candidate=True,
    )

    assert activated == []
    assert result["status"] == "ready_for_manual_activation"
    assert result["candidate"]["registered_model_id"] == "candidate-id"
    assert isinstance(result.get("gate"), dict)
    assert result["gate"]["schema"] == "mimirq.ltr_rollout_gate_result.v1"
    assert result["gate"]["passed"] is True
    assert (tmp_path / "workflow" / "cases.bundle.json").exists()
    assert (tmp_path / "workflow" / "candidate.model.json").exists()
    assert (tmp_path / "workflow" / "candidate.eval.json").exists()
    assert (tmp_path / "workflow" / "baseline.eval.json").exists()
    assert (tmp_path / "workflow" / "comparison.json").exists()
    comparison = json.loads((tmp_path / "workflow" / "comparison.json").read_text(encoding="utf-8"))
    assert isinstance(comparison.get("gate"), dict)
    assert comparison["gate"]["passed"] is True
    workflow = json.loads((tmp_path / "workflow" / "workflow.json").read_text(encoding="utf-8"))
    assert workflow["activation"]["performed"] is False
    assert workflow["comparison"]["baseline_source"] == "active_ltr_model"
    assert isinstance(workflow.get("gate"), dict)
    assert workflow["gate"]["passed"] is True


def test_prepare_ltr_rollout_emits_canary_activation_plan_after_gate_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.ltr_rollout_workflow import FeedbackCaseMaterialization

    mod = _load_rollout_script()

    dataset_id = uuid.uuid4()
    suite = EvidenceSuite(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dataset_id=dataset_id,
        name="gold",
        description=None,
        tags=[],
        config={},
        created_by="u",
    )
    evidence_item = EvidenceItem(
        id=uuid.uuid4(),
        tenant_id=suite.tenant_id,
        dataset_id=dataset_id,
        suite_id=suite.id,
        status="approved",
        query="Q1",
        expected_answer="A1",
        tags=["gold"],
        source_metadata={},
        reference_sources=[{"document_id": str(uuid.uuid4()), "chunk_id": str(uuid.uuid4())}],
        retrieval_snapshot={},
        rag_config_snapshot={},
        notes=None,
        regression_case_id=None,
        created_by="u",
    )
    feedback_case = FeedbackCaseMaterialization(
        feedback_id=str(uuid.uuid4()),
        dataset_id=str(dataset_id),
        question="Q2",
        expected_answer="A2",
        reference_sources=[{"document_id": str(uuid.uuid4()), "chunk_id": str(uuid.uuid4())}],
        tags=["neg"],
        extra={"rating": 2},
    )

    baseline_model = tmp_path / "baseline-model.json"
    baseline_model.write_text("{\"baseline\":true}\n", encoding="utf-8")
    baseline_manifest = tmp_path / "baseline-manifest.json"
    baseline_manifest.write_text("{\"schema\":\"mimirq.ltr_model_manifest.v1\"}\n", encoding="utf-8")

    def _fake_train(*, cases_path: Path, out_model_path: Path, out_manifest_path: Path, **_kwargs) -> None:
        assert cases_path.exists()
        out_model_path.write_text("{\"candidate\":true}\n", encoding="utf-8")
        out_manifest_path.write_text(
            json.dumps(
                {
                    "schema": "mimirq.ltr_model_manifest.v1",
                    "model_sha256": "a" * 64,
                    "feature_schema": "mimirq.ltr_features.v1",
                    "feature_names": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def _fake_eval(*, model_path: Path, out_json_path: Path, **_kwargs) -> None:
        summary = {
            "schema": "mimirq.ltr_offline_eval.v1",
            "cases_total": 2,
            "cases_used": 2,
            "k": 20,
            "top_k": 50,
            "baseline": {"hit": 0.4, "mrr": 0.3, "recall": 0.5, "ndcg": 0.35},
            "ltr": {"hit": 0.7, "mrr": 0.65, "recall": 0.8, "ndcg": 0.7},
            "lineage": {"model_sha256": ("c" if "candidate" in model_path.name else "b") * 64},
        }
        if "baseline" in model_path.name:
            summary["ltr"] = {"hit": 0.5, "mrr": 0.45, "recall": 0.6, "ndcg": 0.5}
        out_json_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_run_train", _fake_train, raising=True)
    monkeypatch.setattr(mod, "_run_eval", _fake_eval, raising=True)
    monkeypatch.setattr(mod, "resolve_active_model_paths", lambda: (str(baseline_model), str(baseline_manifest), 1, "baseline-id"), raising=True)
    monkeypatch.setattr(
        mod,
        "register_model",
        lambda *, model_bytes, _manifest_bytes, _actor_id: type(
            "RegisteredModel",
            (),
            {"model_id": "candidate-id", "model_sha256": "a" * 64, "size_bytes": len(model_bytes), "feature_spec_version": 1},
        )(),
        raising=True,
    )

    result = mod.prepare_ltr_rollout(
        workflow_dir=tmp_path / "workflow",
        base_url="http://localhost:8000/api/v1",
        tenant_id=str(uuid.uuid4()),
        user_id="operator",
        suite=suite,
        evidence_items=[evidence_item],
        feedback_cases=[feedback_case],
        register_candidate=True,
        canary_on_pass=True,
        canary_ratio=0.15,
    )

    assert result["gate"]["passed"] is True
    assert result["activation"]["status"] == "canary_activation_ready"
    assert abs(float(result["activation"]["canary_ratio"]) - 0.15) <= 1e-9
