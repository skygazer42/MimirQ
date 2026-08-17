#!/usr/bin/env python3

import argparse
import importlib.util
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.chat import Conversation, Message  # noqa: E402
from app.models.evidence import EvidenceItem, EvidenceSuite  # noqa: E402
from app.models.feedback import MessageFeedback  # noqa: E402
from app.services.ltr_model_registry import register_model, resolve_active_model_paths  # noqa: E402
from app.services.ltr_rollout_workflow import (  # noqa: E402
    FeedbackCaseMaterialization,
    build_ltr_rollout_activation_plan,
    build_rollout_comparison,
    build_rollout_regression_bundle,
    evaluate_ltr_rollout_gate,
    materialize_feedback_case,
    normalize_ltr_rollout_gate_thresholds,
    sha256_file,
    write_json,
)
from app.services.rag_trace_service import list_rag_traces  # noqa: E402


def activate_model(*_args, **_kwargs):  # pragma: no cover
    raise RuntimeError("activation remains manual; prepare_ltr_rollout must not activate models")


_DEFAULT_LTR_OBJECTIVE = "rank:pairwise"


def _load_script_module(*, name: str, filename: str):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load script module: {filename}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _run_train(
    *,
    cases_path: Path,
    out_model_path: Path,
    out_manifest_path: Path,
    base_url: str,
    tenant_id: str,
    user_id: str,
    bearer: str,
    feature_spec_version: int,
    retrieval_profile: str,
    retrieval_mode: str,
    top_k: int,
    score_threshold: float,
    alpha: float,
    num_boost_round: int,
    seed: int,
    objective: str,
) -> None:
    mod = _load_script_module(name="train_ltr_from_regression_cases", filename="train_ltr_from_regression_cases.py")
    argv = [
        "--cases",
        str(cases_path),
        "--out-model",
        str(out_model_path),
        "--out-manifest",
        str(out_manifest_path),
        "--base-url",
        str(base_url),
        "--tenant-id",
        str(tenant_id),
        "--user-id",
        str(user_id),
        "--feature-spec-version",
        str(int(feature_spec_version or 1)),
        "--retrieval-profile",
        str(retrieval_profile),
        "--retrieval-mode",
        str(retrieval_mode),
        "--top-k",
        str(int(top_k or 0)),
        "--score-threshold",
        str(float(score_threshold or 0.0)),
        "--alpha",
        str(float(alpha or 0.0)),
        "--num-boost-round",
        str(int(num_boost_round or 0)),
        "--seed",
        str(int(seed or 0)),
        "--objective",
        str(objective or _DEFAULT_LTR_OBJECTIVE),
    ]
    if bearer:
        argv.extend(["--bearer", str(bearer)])
    rc = int(mod.main(argv))
    if rc != 0:
        raise RuntimeError(f"train_ltr_from_regression_cases failed with exit code {rc}")


def _run_eval(
    *,
    cases_path: Path,
    model_path: Path,
    out_json_path: Path,
    base_url: str,
    tenant_id: str,
    user_id: str,
    bearer: str,
    feature_spec_version: int,
    retrieval_profile: str,
    retrieval_mode: str,
    top_k: int,
    score_threshold: float,
    alpha: float,
    k: int,
    rerank_top_n: int,
) -> None:
    mod = _load_script_module(name="eval_ltr_offline", filename="eval_ltr_offline.py")
    argv = [
        "--cases",
        str(cases_path),
        "--model",
        str(model_path),
        "--out-json",
        str(out_json_path),
        "--base-url",
        str(base_url),
        "--tenant-id",
        str(tenant_id),
        "--user-id",
        str(user_id),
        "--feature-spec-version",
        str(int(feature_spec_version or 1)),
        "--retrieval-profile",
        str(retrieval_profile),
        "--retrieval-mode",
        str(retrieval_mode),
        "--top-k",
        str(int(top_k or 0)),
        "--score-threshold",
        str(float(score_threshold or 0.0)),
        "--alpha",
        str(float(alpha or 0.0)),
        "--k",
        str(int(k or 0)),
        "--rerank-top-n",
        str(int(rerank_top_n or 0)),
    ]
    if bearer:
        argv.extend(["--bearer", str(bearer)])
    rc = int(mod.main(argv))
    if rc != 0:
        raise RuntimeError(f"eval_ltr_offline failed with exit code {rc}")


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected JSON object at {path}")
    return raw


def _read_gate_thresholds(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = _read_json(path)
    return normalize_ltr_rollout_gate_thresholds(payload)


def _find_trace_by_request_id(*, tenant_id: UUID, conversation_id: UUID, request_id: str) -> dict[str, Any] | None:
    rid = str(request_id or "").strip()
    if not rid:
        return None
    try:
        traces = list_rag_traces(
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            limit=100,
            window_minutes=7 * 24 * 60,
            max_bytes=10_000_000,
        )
    except Exception:
        return None
    for item in getattr(traces, "items", []) or []:
        if str(getattr(item, "request_id", "") or "") != rid:
            continue
        if hasattr(item, "model_dump"):
            payload = item.model_dump(mode="json")
            return payload if isinstance(payload, dict) else None
        if isinstance(item, dict):
            return dict(item)
    return None


def _collect_suite_evidence(
    *,
    db: Session,
    tenant_id: UUID,
    suite_id: UUID,
) -> tuple[EvidenceSuite, list[EvidenceItem]]:
    suite = db.query(EvidenceSuite).filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id).first()
    if suite is None:
        raise ValueError(f"evidence suite not found: {suite_id}")
    items = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.tenant_id == tenant_id,
            EvidenceItem.suite_id == suite_id,
            EvidenceItem.status == "approved",
        )
        .order_by(EvidenceItem.updated_at.desc())
        .all()
    )
    return suite, list(items or [])


def _collect_feedback_cases(
    *,
    db: Session,
    tenant_id: UUID,
    feedback_ids: Sequence[UUID],
) -> list[FeedbackCaseMaterialization]:
    out: list[FeedbackCaseMaterialization] = []
    for feedback_id in feedback_ids or []:
        feedback = (
            db.query(MessageFeedback)
            .filter(MessageFeedback.id == feedback_id, MessageFeedback.tenant_id == tenant_id)
            .first()
        )
        if feedback is None:
            raise ValueError(f"feedback not found: {feedback_id}")
        assistant = db.query(Message).filter(Message.id == feedback.message_id, Message.tenant_id == tenant_id).first()
        if assistant is None:
            raise ValueError(f"assistant message not found for feedback: {feedback_id}")
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == feedback.conversation_id, Conversation.tenant_id == tenant_id)
            .first()
        )
        if conversation is None:
            raise ValueError(f"conversation not found for feedback: {feedback_id}")
        user_message = (
            db.query(Message)
            .filter(
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation.id,
                Message.role == "user",
                Message.created_at <= assistant.created_at,
            )
            .order_by(Message.created_at.desc())
            .first()
        )
        meta = assistant.message_metadata if isinstance(getattr(assistant, "message_metadata", None), dict) else {}
        trace_payload = _find_trace_by_request_id(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            request_id=str(meta.get("request_id") or "").strip(),
        )
        out.append(
            materialize_feedback_case(
                feedback=feedback,
                assistant=assistant,
                conversation=conversation,
                user_message=user_message,
                trace_payload=trace_payload,
            )
        )
    return out


def _default_workflow_dir() -> Path:
    root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return (root / ".ltr_rollouts" / stamp).resolve(strict=False)


def prepare_ltr_rollout(
    *,
    workflow_dir: Path,
    base_url: str,
    tenant_id: str,
    user_id: str,
    suite: EvidenceSuite | None,
    evidence_items: Sequence[EvidenceItem] | None,
    feedback_cases: Sequence[FeedbackCaseMaterialization] | None,
    bearer: str = "",
    register_candidate: bool = True,
    feature_spec_version: int = 1,
    retrieval_profile: str = "recall50",
    retrieval_mode: str = "hybrid",
    top_k: int = 50,
    score_threshold: float = 0.0,
    alpha: float = 0.6,
    num_boost_round: int = 50,
    seed: int = 42,
    objective: str = _DEFAULT_LTR_OBJECTIVE,
    eval_k: int = 20,
    rerank_top_n: int = 30,
    gate_thresholds: dict[str, Any] | None = None,
    canary_on_pass: bool = False,
    canary_ratio: float | None = None,
) -> dict[str, Any]:
    workflow_dir = Path(workflow_dir)
    workflow_dir.mkdir(parents=True, exist_ok=True)
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    workflow_json_path = workflow_dir / "workflow.json"

    dataset_id = str(suite.dataset_id) if suite is not None else ""
    if not dataset_id:
        for case in feedback_cases or []:
            if case.dataset_id:
                dataset_id = str(case.dataset_id)
                break
    if not dataset_id:
        raise ValueError("dataset_id could not be resolved from suite or feedback cases")

    try:
        cases_bundle = build_rollout_regression_bundle(
            dataset_id=dataset_id,
            suite=suite,
            evidence_items=evidence_items,
            feedback_cases=feedback_cases,
            generated_at=generated_at,
        )

        cases_path = workflow_dir / "cases.bundle.json"
        candidate_model_path = workflow_dir / "candidate.model.json"
        candidate_manifest_path = workflow_dir / "candidate.manifest.json"
        candidate_eval_path = workflow_dir / "candidate.eval.json"
        baseline_eval_path = workflow_dir / "baseline.eval.json"
        comparison_path = workflow_dir / "comparison.json"

        write_json(cases_path, cases_bundle)

        _run_train(
            cases_path=cases_path,
            out_model_path=candidate_model_path,
            out_manifest_path=candidate_manifest_path,
            base_url=base_url,
            tenant_id=tenant_id,
            user_id=user_id,
            bearer=bearer,
            feature_spec_version=feature_spec_version,
            retrieval_profile=retrieval_profile,
            retrieval_mode=retrieval_mode,
            top_k=top_k,
            score_threshold=score_threshold,
            alpha=alpha,
            num_boost_round=num_boost_round,
            seed=seed,
            objective=objective,
        )
        _run_eval(
            cases_path=cases_path,
            model_path=candidate_model_path,
            out_json_path=candidate_eval_path,
            base_url=base_url,
            tenant_id=tenant_id,
            user_id=user_id,
            bearer=bearer,
            feature_spec_version=feature_spec_version,
            retrieval_profile=retrieval_profile,
            retrieval_mode=retrieval_mode,
            top_k=top_k,
            score_threshold=score_threshold,
            alpha=alpha,
            k=eval_k,
            rerank_top_n=rerank_top_n,
        )

        active_model_path, _active_manifest_path, active_spec_version, active_model_id = resolve_active_model_paths()
        baseline_eval: dict[str, Any] | None = None
        if active_model_path:
            _run_eval(
                cases_path=cases_path,
                model_path=Path(active_model_path),
                out_json_path=baseline_eval_path,
                base_url=base_url,
                tenant_id=tenant_id,
                user_id=user_id,
                bearer=bearer,
                feature_spec_version=int(active_spec_version or feature_spec_version or 1),
                retrieval_profile=retrieval_profile,
                retrieval_mode=retrieval_mode,
                top_k=top_k,
                score_threshold=score_threshold,
                alpha=alpha,
                k=eval_k,
                rerank_top_n=rerank_top_n,
            )
            baseline_eval = _read_json(baseline_eval_path)

        registered_model_id: str | None = None
        if register_candidate:
            registered = register_model(
                model_bytes=candidate_model_path.read_bytes(),
                _manifest_bytes=candidate_manifest_path.read_bytes(),
                _actor_id=user_id,
            )
            registered_model_id = str(getattr(registered, "model_id", "") or "") or None

        candidate_eval = _read_json(candidate_eval_path)
        comparison = build_rollout_comparison(
            generated_at=generated_at,
            candidate_eval=candidate_eval,
            baseline_eval=baseline_eval,
            active_model_id=active_model_id,
            candidate_model_id=registered_model_id,
        )
        gate = evaluate_ltr_rollout_gate(
            comparison=comparison,
            thresholds=gate_thresholds,
            generated_at=generated_at,
        )
        activation = build_ltr_rollout_activation_plan(
            gate=gate,
            candidate_model_id=registered_model_id,
            actor_id=user_id,
            canary_on_pass=bool(canary_on_pass),
            canary_ratio=canary_ratio,
        )
        comparison["activation"] = activation
        comparison["gate"] = gate
        write_json(comparison_path, comparison)

        result = {
            "schema": "mimirq.ltr_rollout_workflow.v1",
            "generated_at": generated_at,
            "status": "ready_for_manual_activation",
            "dataset_id": dataset_id,
            "sources": dict(cases_bundle.get("source_summary") or {}),
            "artifacts": {
                "cases_bundle": {"path": str(cases_path), "sha256": sha256_file(cases_path)},
                "candidate_model": {"path": str(candidate_model_path), "sha256": sha256_file(candidate_model_path)},
                "candidate_manifest": {
                    "path": str(candidate_manifest_path),
                    "sha256": sha256_file(candidate_manifest_path),
                },
                "candidate_eval": {"path": str(candidate_eval_path), "sha256": sha256_file(candidate_eval_path)},
                "baseline_eval": (
                    {"path": str(baseline_eval_path), "sha256": sha256_file(baseline_eval_path)}
                    if baseline_eval is not None
                    else None
                ),
                "comparison": {"path": str(comparison_path), "sha256": sha256_file(comparison_path)},
            },
            "candidate": {
                "registered_model_id": registered_model_id,
                "model_path": str(candidate_model_path),
                "manifest_path": str(candidate_manifest_path),
            },
            "baseline": {
                "active_model_id": active_model_id,
                "active_model_path": active_model_path,
            },
            "comparison": comparison,
            "gate": gate,
            "activation": dict(activation),
        }
        write_json(workflow_json_path, result)
        return result
    except Exception as exc:
        failure = {
            "schema": "mimirq.ltr_rollout_workflow.v1",
            "generated_at": generated_at,
            "status": "failed",
            "error": str(exc)[:400],
            "activation": {"performed": False, "status": "manual_review_required"},
        }
        write_json(workflow_json_path, failure)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a bounded LTR rollout from approved evidence and selected feedback."
    )
    parser.add_argument("--suite-id", default="", help="EvidenceSuite id to source approved evidence from")
    parser.add_argument(
        "--feedback-id", action="append", default=[], help="Feedback id to materialize into rollout cases (repeatable)"
    )
    parser.add_argument(
        "--workflow-dir",
        default="",
        help="Directory to write workflow artifacts (default: uploads/.ltr_rollouts/<timestamp>)",
    )
    parser.add_argument(
        "--base-url", default="http://localhost:8000/api/v1", help="API base URL for train/eval scripts"
    )
    parser.add_argument("--tenant-id", required=True, help="Tenant id")
    parser.add_argument("--user-id", default="ltr-rollout-cli", help="Actor id for registry lineage")
    parser.add_argument("--bearer", default="", help="Bearer token for API requests")
    parser.add_argument(
        "--skip-register", action="store_true", help="Do not register the candidate model in the local LTR registry"
    )
    parser.add_argument("--feature-spec-version", type=int, default=1, help="LTR feature spec version")
    parser.add_argument("--retrieval-profile", default="recall50", help="Retrieval profile for train/eval")
    parser.add_argument("--retrieval-mode", default="hybrid", help="Retrieval mode for train/eval")
    parser.add_argument("--top-k", type=int, default=50, help="Evidence API top-k for train/eval")
    parser.add_argument(
        "--score-threshold", type=float, default=0.0, help="Evidence API score threshold for train/eval"
    )
    parser.add_argument("--alpha", type=float, default=0.6, help="Fusion alpha for train/eval")
    parser.add_argument("--num-boost-round", type=int, default=50, help="LTR training rounds")
    parser.add_argument("--seed", type=int, default=42, help="Training seed")
    parser.add_argument("--objective", default=_DEFAULT_LTR_OBJECTIVE, help="LTR training objective")
    parser.add_argument("--eval-k", type=int, default=20, help="Metric cutoff for offline eval")
    parser.add_argument("--rerank-top-n", type=int, default=30, help="Local rerank prefix for offline eval")
    parser.add_argument("--gate-thresholds", default="", help="Optional path to gate thresholds JSON")
    parser.add_argument("--gate-min-delta-hit", type=float, default=None, help="Override threshold for delta.hit")
    parser.add_argument("--gate-min-delta-mrr", type=float, default=None, help="Override threshold for delta.mrr")
    parser.add_argument("--gate-min-delta-recall", type=float, default=None, help="Override threshold for delta.recall")
    parser.add_argument("--gate-min-delta-ndcg", type=float, default=None, help="Override threshold for delta.ndcg")
    parser.add_argument(
        "--gate-min-cases-used", type=float, default=None, help="Override threshold for candidate.cases_used"
    )
    parser.add_argument(
        "--canary-on-pass",
        action="store_true",
        help="When gate decision is pass, emit canary activation plan into workflow/comparison artifacts.",
    )
    parser.add_argument(
        "--canary-ratio",
        type=float,
        default=None,
        help="Optional canary ratio override in [0,1]. Empty uses gate policy decision ratio.",
    )
    args = parser.parse_args(argv)

    suite_id = str(args.suite_id or "").strip()
    feedback_ids = [str(value or "").strip() for value in (args.feedback_id or []) if str(value or "").strip()]
    if not suite_id and not feedback_ids:
        print("[prepare_ltr_rollout] ERROR: provide --suite-id and/or at least one --feedback-id", file=sys.stderr)
        return 2

    workflow_dir = Path(args.workflow_dir) if str(args.workflow_dir or "").strip() else _default_workflow_dir()
    tenant_uuid = UUID(str(args.tenant_id))
    suite: EvidenceSuite | None = None
    evidence_items: list[EvidenceItem] = []
    feedback_cases: list[FeedbackCaseMaterialization] = []
    thresholds_path = Path(str(args.gate_thresholds or "").strip()) if str(args.gate_thresholds or "").strip() else None
    gate_thresholds = _read_gate_thresholds(thresholds_path)

    metrics_overrides: dict[str, dict[str, float]] = {}
    for metric, value in (
        ("delta.hit", args.gate_min_delta_hit),
        ("delta.mrr", args.gate_min_delta_mrr),
        ("delta.recall", args.gate_min_delta_recall),
        ("delta.ndcg", args.gate_min_delta_ndcg),
        ("candidate.cases_used", args.gate_min_cases_used),
    ):
        if value is None:
            continue
        metrics_overrides[metric] = {"min": float(value)}
    if metrics_overrides:
        merged = normalize_ltr_rollout_gate_thresholds(gate_thresholds)
        merged_metrics = dict(merged.get("metrics") or {})
        merged_metrics.update(metrics_overrides)
        merged["metrics"] = merged_metrics
        gate_thresholds = merged

    db = SessionLocal()
    try:
        if suite_id:
            suite, evidence_items = _collect_suite_evidence(db=db, tenant_id=tenant_uuid, suite_id=UUID(suite_id))
        if feedback_ids:
            feedback_cases = _collect_feedback_cases(
                db=db,
                tenant_id=tenant_uuid,
                feedback_ids=[UUID(value) for value in feedback_ids],
            )
    finally:
        db.close()

    result = prepare_ltr_rollout(
        workflow_dir=workflow_dir,
        base_url=str(args.base_url),
        tenant_id=str(args.tenant_id),
        user_id=str(args.user_id),
        suite=suite,
        evidence_items=evidence_items,
        feedback_cases=feedback_cases,
        bearer=str(args.bearer),
        register_candidate=not bool(args.skip_register),
        feature_spec_version=int(args.feature_spec_version or 1),
        retrieval_profile=str(args.retrieval_profile),
        retrieval_mode=str(args.retrieval_mode),
        top_k=int(args.top_k or 0),
        score_threshold=float(args.score_threshold or 0.0),
        alpha=float(args.alpha or 0.0),
        num_boost_round=int(args.num_boost_round or 0),
        seed=int(args.seed or 0),
        objective=str(args.objective),
        eval_k=int(args.eval_k or 0),
        rerank_top_n=int(args.rerank_top_n or 0),
        gate_thresholds=gate_thresholds,
        canary_on_pass=bool(args.canary_on_pass),
        canary_ratio=(float(args.canary_ratio) if args.canary_ratio is not None else None),
    )

    print(
        "[prepare_ltr_rollout] OK"
        f" workflow_dir={workflow_dir}"
        f" dataset_id={result['dataset_id']}"
        f" cases={result['sources']['total_items']}"
        f" candidate_model_id={result['candidate']['registered_model_id'] or '<unregistered>'}"
        f" baseline_source={result['comparison']['baseline_source']}"
        f" gate_passed={result['gate']['passed']}"
        f" activation={result['activation']['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
