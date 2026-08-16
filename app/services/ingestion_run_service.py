"""
Ingestion run manifest service.

Design goals:
- Best-effort observability: never block ingestion because a run manifest update failed.
- Bounded stats: keep JSON payloads small and stable for UI/report exports.
"""


from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ingestion_run import IngestionRun, IngestionRunDocument
from app.rag.core.logging import get_logger

logger = get_logger(__name__)
_INGESTION_RUN_FALLBACK_LOG_MESSAGE = "Ignoring non-critical ingestion-run fallback failure: %s"
_INGESTION_RUN_DOCUMENT_UNIQUE_CONSTRAINT = "uq_ingestion_run_documents_tenant_run_document"
_TERMINAL_DOCUMENT_STATUSES = ("completed", "failed", "quarantined", "cancelled")
IngestionRunCriticality = Literal["best_effort", "required"]


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _safe_int(v: object, *, default: int = 0) -> int:
    try:
        return int(v or 0)
    except Exception:
        return int(default)


def _normalize_status(value: object) -> str:
    s = str(value or "").strip().lower()
    return s or "unknown"


def _failure_reason(error_message: object) -> str:
    """
    Best-effort error bucket key.

    We intentionally avoid leaking long exception strings into run stats.
    """
    msg = str(error_message or "").strip()
    if not msg:
        return "unknown"
    # Prefer prefix-style codes: "preprocess_failed: ..." / "parse_failed: ..." etc.
    head = msg.splitlines()[0].strip()
    for sep in (":", " - ", " — "):
        if sep in head:
            key = head.split(sep, 1)[0].strip().lower()
            if 2 <= len(key) <= 64 and all(ch.isalnum() or ch in {"_", ".", "-"} for ch in key):
                return key
    # Fall back to a short normalized token.
    return head[:64].strip().lower().replace(" ", "_") or "unknown"


def _init_run_stats(stats: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(stats or {})
    base.setdefault("v", "1")
    base.setdefault("total_documents", 0)
    base.setdefault("status_counts", {})
    base.setdefault("failure_reasons_top", {})
    base.setdefault("stage_durations_ms_sum", {})
    base.setdefault("stage_durations_docs", 0)
    return base


def _completion_target_for_run(run: IngestionRun | Any, *, stats: dict[str, Any]) -> int:
    total_docs = _safe_int(stats.get("total_documents"), default=0)
    config = getattr(run, "config", None)
    expected_docs = _safe_int(config.get("expected_documents"), default=0) if isinstance(config, dict) else 0
    if expected_docs <= 0:
        return total_docs
    return max(total_docs, expected_docs)


def _bump_counter(mapping: dict[str, Any], key: str, delta: int) -> None:
    if not key:
        return
    cur = _safe_int(mapping.get(key), default=0)
    nxt = max(0, cur + int(delta))
    if nxt <= 0:
        mapping.pop(key, None)
    else:
        mapping[key] = int(nxt)


def _is_duplicate_run_document_integrity_error(exc: IntegrityError) -> bool:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    if str(getattr(diag, "constraint_name", "") or "").strip() == _INGESTION_RUN_DOCUMENT_UNIQUE_CONSTRAINT:
        return True
    message = str(getattr(exc, "orig", "") or exc)
    return _INGESTION_RUN_DOCUMENT_UNIQUE_CONSTRAINT in message


def _lock_run_for_update(db: Session, *, tenant_id: UUID, run_id: UUID) -> IngestionRun | None:
    return (
        db.query(IngestionRun)
        .filter(IngestionRun.id == run_id, IngestionRun.tenant_id == tenant_id)
        .with_for_update()
        .first()
    )


def _complete_transaction_quietly(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as rollback_exc:
            logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, rollback_exc)


def _normalize_criticality(value: object) -> IngestionRunCriticality:
    raw = str(value or "").strip().lower()
    return "required" if raw == "required" else "best_effort"


def _handle_ingestion_run_failure(
    db: Session,
    *,
    exc: Exception,
    criticality: IngestionRunCriticality,
) -> None:
    try:
        db.rollback()
    except Exception as rollback_exc:
        logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, rollback_exc)
    if criticality == "required":
        raise exc


def _update_progress_and_finalize_run(
    run: IngestionRun | Any,
    *,
    stats: dict[str, Any],
    finished_at: datetime,
) -> tuple[str | None, str | None, float | None] | None:
    sc = stats.get("status_counts")
    sc = sc if isinstance(sc, dict) else {}
    total_docs = _safe_int(stats.get("total_documents"), default=0)
    terminal = sum(_safe_int(sc.get(k), default=0) for k in _TERMINAL_DOCUMENT_STATUSES)
    completion_target = _completion_target_for_run(run, stats=stats)
    progress = int((terminal / max(1, completion_target)) * 100) if completion_target > 0 else 0
    stats["progress"] = max(0, min(100, progress))
    if completion_target <= 0 or total_docs < completion_target or terminal < completion_target:
        return None

    completed = _safe_int(sc.get("completed"), default=0)
    failed = _safe_int(sc.get("failed"), default=0)
    cancelled = _safe_int(sc.get("cancelled"), default=0)
    quarantined = _safe_int(sc.get("quarantined"), default=0)
    if cancelled >= total_docs and completed == 0 and failed == 0 and quarantined == 0:
        run.status = "cancelled"
    elif completed == 0 and (failed + quarantined) >= total_docs:
        run.status = "failed"
    else:
        run.status = "completed"
    if run.finished_at is not None:
        return None
    run.finished_at = finished_at
    try:
        dur = None
        if run.started_at is not None and run.finished_at is not None:
            dur = float((run.finished_at - run.started_at).total_seconds())
        return getattr(run, "kind", None), getattr(run, "status", None), dur
    except Exception:
        return getattr(run, "kind", None), getattr(run, "status", None), None


def _bounded_reason_counts(reasons: list[object] | tuple[object, ...] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reason in reasons or []:
        key = _failure_reason(reason)
        _bump_counter(counts, key, +1)
    if len(counts) > 25:
        ranked = sorted(((k, _safe_int(v)) for k, v in counts.items()), key=lambda kv: (-kv[1], kv[0]))
        counts = {k: int(v) for k, v in ranked[:20] if v > 0}
    return counts


def _counts_by_normalized_status(statuses: list[object] | tuple[object, ...] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in statuses or []:
        _bump_counter(counts, _normalize_status(status), +1)
    return counts


class IngestionRunService:
    @staticmethod
    def create_run(
        db: Session,
        *,
        tenant_id: UUID,
        dataset_id: UUID | None,
        requested_by: str | None,
        kind: str,
        config: dict[str, Any] | None = None,
        expected_documents: int | None = None,
    ) -> IngestionRun:
        run = IngestionRun(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            kind=str(kind or "unknown")[:80],
            requested_by=(str(requested_by)[:255] if requested_by else None),
            status="running",
            config=dict(config or {}),
            stats=_init_run_stats({}),
            error_message=None,
            started_at=_now_utc(),
        )
        if expected_documents is not None:
            run.config["expected_documents"] = max(0, int(expected_documents))
        db.add(run)
        db.commit()
        db.refresh(run)
        try:
            from app.services.ingestion_prometheus_metrics import observe_ingestion_run_created

            observe_ingestion_run_created(kind=run.kind)
        except Exception as exc:
            logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, exc)
        return run

    @staticmethod
    def add_document(
        db: Session,
        *,
        tenant_id: UUID,
        run_id: UUID,
        document_id: UUID,
        source_ref: str | None = None,
        initial_status: str = "created",
        doc_meta: dict[str, Any] | None = None,
    ) -> None:
        """
        Attach a document to a run and update bounded run stats.
        """
        try:
            run = _lock_run_for_update(db, tenant_id=tenant_id, run_id=run_id)
        except Exception:
            try:
                db.rollback()
            except Exception as exc:
                logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, exc)
            run = None
        if run is None:
            return

        try:
            existing = (
                db.query(IngestionRunDocument)
                .filter(
                    IngestionRunDocument.tenant_id == tenant_id,
                    IngestionRunDocument.run_id == run_id,
                    IngestionRunDocument.document_id == document_id,
                )
                .with_for_update()
                .first()
            )
        except Exception:
            existing = None
        if existing is not None:
            _complete_transaction_quietly(db)
            return

        row = IngestionRunDocument(
            tenant_id=tenant_id,
            run_id=run_id,
            document_id=document_id,
            source_ref=(str(source_ref)[:1000] if source_ref else None),
            status=_normalize_status(initial_status),
        )
        db.add(row)

        finished_meta: tuple[str | None, str | None, float | None] | None = None
        try:
            flush = getattr(db, "flush", None)
            if callable(flush):
                flush()
        except IntegrityError as exc:
            try:
                db.rollback()
            except Exception as rollback_exc:
                logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, rollback_exc)
            if _is_duplicate_run_document_integrity_error(exc):
                return
            return
        except Exception:
            try:
                db.rollback()
            except Exception as rollback_exc:
                logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, rollback_exc)
            return

        try:
            stats = _init_run_stats(dict(getattr(run, "stats", None) or {}))
            stats["total_documents"] = _safe_int(stats.get("total_documents"), default=0) + 1
            sc = stats.get("status_counts")
            sc = sc if isinstance(sc, dict) else {}
            _bump_counter(sc, _normalize_status(initial_status), +1)
            stats["status_counts"] = sc

            finished_meta = _update_progress_and_finalize_run(run, stats=stats, finished_at=_now_utc())

            # Track pipeline version distribution (best-effort) to support run compare/audit.
            meta = doc_meta if isinstance(doc_meta, dict) else {}
            ph = str(meta.get("pipeline_hash") or "").strip()
            if ph:
                dist = stats.get("pipeline_hash_docs")
                dist = dist if isinstance(dist, dict) else {}
                _bump_counter(dist, ph[:64], +1)
                stats["pipeline_hash_docs"] = dist

            run.stats = stats
        except Exception as exc:
            # Stats update is best-effort; keep the mapping row.
            logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, exc)

        try:
            db.commit()
        except IntegrityError as exc:
            try:
                db.rollback()
            except Exception as rollback_exc:
                logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, rollback_exc)
            if _is_duplicate_run_document_integrity_error(exc):
                return
            return
        except Exception:
            try:
                db.rollback()
            except Exception as rollback_exc:
                logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, rollback_exc)
            # Best-effort only; callers should not fail ingestion because of manifest.
            return
        if finished_meta is not None:
            try:
                from app.services.ingestion_prometheus_metrics import observe_ingestion_run_finished

                kind, status, dur = finished_meta
                observe_ingestion_run_finished(kind=kind, status=status, duration_sec=dur)
            except Exception as exc:
                logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, exc)

    @staticmethod
    def on_document_status_update(
        db: Session,
        *,
        tenant_id: UUID,
        document_id: UUID,
        new_status: str,
        error_message: str | None = None,
        doc_meta: dict[str, Any] | None = None,
        criticality: IngestionRunCriticality = "best_effort",
    ) -> None:
        """
        Best-effort: update run manifest records when a document changes status.
        """
        status_norm = _normalize_status(new_status)
        criticality_norm = _normalize_criticality(criticality)

        target_run_id: UUID | None = None
        if isinstance(doc_meta, dict):
            raw = doc_meta.get("last_ingestion_run_id") or doc_meta.get("created_by_run_id")
            if raw:
                try:
                    target_run_id = UUID(str(raw))
                except Exception:
                    target_run_id = None

        def _candidate_rows_for_run_ids(*, run_filter: UUID | None) -> list[IngestionRunDocument]:
            q = db.query(IngestionRunDocument).filter(
                IngestionRunDocument.tenant_id == tenant_id,
                IngestionRunDocument.document_id == document_id,
            )
            if run_filter is not None:
                q = q.filter(IngestionRunDocument.run_id == run_filter)
            return q.order_by(IngestionRunDocument.run_id, IngestionRunDocument.id).all()

        try:
            rows = _candidate_rows_for_run_ids(run_filter=target_run_id)
        except Exception as exc:
            _handle_ingestion_run_failure(db, exc=exc, criticality=criticality_norm)
            return
        if not rows and target_run_id is not None:
            # Backward-compatible fallback: if metadata was missing/malformed, update any active run attachments.
            try:
                rows = _candidate_rows_for_run_ids(run_filter=None)
            except Exception as exc:
                _handle_ingestion_run_failure(db, exc=exc, criticality=criticality_norm)
                return
        if not rows:
            return

        candidate_run_ids = sorted({row.run_id for row in rows}, key=str)
        locked_runs: dict[UUID, IngestionRun] = {}
        for run_id in candidate_run_ids:
            try:
                run = _lock_run_for_update(db, tenant_id=tenant_id, run_id=run_id)
            except Exception as exc:
                _handle_ingestion_run_failure(db, exc=exc, criticality=criticality_norm)
                run = None
            if run is not None:
                locked_runs[run_id] = run
        if not locked_runs:
            _complete_transaction_quietly(db)
            return

        try:
            rows = (
                db.query(IngestionRunDocument)
                .filter(
                    IngestionRunDocument.tenant_id == tenant_id,
                    IngestionRunDocument.document_id == document_id,
                    IngestionRunDocument.run_id.in_(candidate_run_ids),
                )
                .order_by(IngestionRunDocument.run_id, IngestionRunDocument.id)
                .with_for_update()
                .all()
            )
        except Exception as exc:
            _handle_ingestion_run_failure(db, exc=exc, criticality=criticality_norm)
            return

        # Update each run attachment (a doc may belong to multiple runs, e.g. replays).
        now = _now_utc()
        finished_runs: list[tuple[str | None, str | None, float | None]] = []
        for row in rows:
            run = locked_runs.get(row.run_id)
            if run is None:
                continue
            # Freeze completed runs: a document can be reprocessed later and should not mutate old manifests.
            if getattr(run, "finished_at", None) is not None:
                continue

            prev = _normalize_status(getattr(row, "status", None))
            if prev == status_norm:
                continue
            row.status = status_norm

            stats = _init_run_stats(dict(getattr(run, "stats", None) or {}))
            sc = stats.get("status_counts")
            sc = sc if isinstance(sc, dict) else {}
            _bump_counter(sc, prev, -1)
            _bump_counter(sc, status_norm, +1)
            stats["status_counts"] = sc

            # Failure reasons topN (bounded).
            if status_norm in {"failed", "quarantined"} and error_message:
                fr = stats.get("failure_reasons_top")
                fr = fr if isinstance(fr, dict) else {}
                key = _failure_reason(error_message)
                _bump_counter(fr, key, +1)
                # Cap to top 20 keys by count (best-effort).
                if len(fr) > 25:
                    ranked = sorted(((k, _safe_int(v)) for k, v in fr.items()), key=lambda kv: (-kv[1], kv[0]))
                    fr = {k: int(v) for k, v in ranked[:20] if v > 0}
                stats["failure_reasons_top"] = fr

            # Stage durations aggregation (only when we have terminal status).
            meta = doc_meta if isinstance(doc_meta, dict) else {}
            durations = meta.get("ingest_stage_durations_ms")
            if status_norm in {"completed", "failed", "quarantined", "cancelled"} and isinstance(durations, dict):
                sums = stats.get("stage_durations_ms_sum")
                sums = sums if isinstance(sums, dict) else {}
                for k, v in durations.items():
                    if not isinstance(k, str) or not k.strip():
                        continue
                    sums[k[:64]] = _safe_int(sums.get(k), default=0) + _safe_int(v, default=0)
                stats["stage_durations_ms_sum"] = sums
                stats["stage_durations_docs"] = _safe_int(stats.get("stage_durations_docs"), default=0) + 1

            finished_meta = _update_progress_and_finalize_run(run, stats=stats, finished_at=now)
            if finished_meta is not None:
                finished_runs.append(finished_meta)
                if run.finished_at is not None:
                    # Touch dataset.updated_at so API instances can invalidate dataset-scoped caches
                    # (e.g., in-memory BM25 indices) after ingestion completes.
                    try:
                        ds_id = getattr(run, "dataset_id", None)
                        if ds_id is not None:
                            from app.models.dataset import Dataset  # noqa: WPS433

                            ds = (
                                db.query(Dataset)
                                .filter(Dataset.tenant_id == tenant_id, Dataset.id == ds_id)
                                .first()
                            )
                            if ds is not None:
                                ds.updated_at = now
                    except Exception as exc:
                        logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, exc)

            run.stats = stats
        try:
            db.commit()
        except Exception as exc:
            _handle_ingestion_run_failure(db, exc=exc, criticality=criticality_norm)
            return
        if finished_runs:
            try:
                from app.services.ingestion_prometheus_metrics import observe_ingestion_run_finished

                for kind, status, dur in finished_runs:
                    observe_ingestion_run_finished(kind=kind, status=status, duration_sec=dur)
            except Exception as exc:
                logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, exc)

    @staticmethod
    def close_intake(
        db: Session,
        *,
        tenant_id: UUID,
        run_id: UUID,
        attempted_inputs: int | None = None,
        rejected_inputs: int = 0,
        rejection_reasons: list[object] | tuple[object, ...] | None = None,
    ) -> None:
        """
        Reconcile the batch intake target with actual attached documents and finalize if possible.
        """
        try:
            run = _lock_run_for_update(db, tenant_id=tenant_id, run_id=run_id)
        except Exception:
            try:
                db.rollback()
            except Exception as rollback_exc:
                logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, rollback_exc)
            return
        if run is None:
            return

        try:
            rows = (
                db.query(IngestionRunDocument)
                .filter(
                    IngestionRunDocument.tenant_id == tenant_id,
                    IngestionRunDocument.run_id == run_id,
                )
                .order_by(IngestionRunDocument.id)
                .all()
            )
        except Exception:
            try:
                db.rollback()
            except Exception as rollback_exc:
                logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, rollback_exc)
            return

        finished_meta: tuple[str | None, str | None, float | None] | None = None
        try:
            stats = _init_run_stats(dict(getattr(run, "stats", None) or {}))
            config = dict(getattr(run, "config", None) or {})

            statuses: dict[str, str] = {}
            for row in rows:
                document_id = getattr(row, "document_id", None)
                if document_id is None:
                    continue
                statuses[str(document_id)] = _normalize_status(getattr(row, "status", None))

            actual_total = len(statuses)
            stats["total_documents"] = actual_total
            stats["status_counts"] = _counts_by_normalized_status(list(statuses.values()))
            if attempted_inputs is not None:
                stats["attempted_inputs"] = max(0, int(attempted_inputs))
            stats["rejected_inputs"] = max(0, int(rejected_inputs))
            stats["rejected_reasons_top"] = _bounded_reason_counts(rejection_reasons)
            config["expected_documents"] = actual_total
            run.config = config

            now = _now_utc()
            finished_meta = _update_progress_and_finalize_run(run, stats=stats, finished_at=now)
            attempted_total = _safe_int(stats.get("attempted_inputs"), default=0)
            rejected_total = _safe_int(stats.get("rejected_inputs"), default=0)
            if (
                finished_meta is None
                and actual_total == 0
                and attempted_total > 0
                and rejected_total >= attempted_total
            ):
                run.status = "failed"
                stats["progress"] = 100
                if run.finished_at is None:
                    run.finished_at = now
                    try:
                        dur = None
                        if run.started_at is not None and run.finished_at is not None:
                            dur = float((run.finished_at - run.started_at).total_seconds())
                        finished_meta = (getattr(run, "kind", None), getattr(run, "status", None), dur)
                    except Exception:
                        finished_meta = (getattr(run, "kind", None), getattr(run, "status", None), None)

            run.stats = stats
        except Exception as exc:
            logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, exc)

        try:
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception as rollback_exc:
                logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, rollback_exc)
            return
        if finished_meta is not None:
            try:
                from app.services.ingestion_prometheus_metrics import observe_ingestion_run_finished

                kind, status, dur = finished_meta
                observe_ingestion_run_finished(kind=kind, status=status, duration_sec=dur)
            except Exception as exc:
                logger.debug(_INGESTION_RUN_FALLBACK_LOG_MESSAGE, exc)

    @staticmethod
    def compare_runs(*, run_a: IngestionRun, run_b: IngestionRun) -> dict[str, Any]:
        """
        Best-effort diff payload for UI.
        """
        a_cfg = dict(getattr(run_a, "config", None) or {})
        b_cfg = dict(getattr(run_b, "config", None) or {})
        a_stats = dict(getattr(run_a, "stats", None) or {})
        b_stats = dict(getattr(run_b, "stats", None) or {})

        cfg_keys = sorted(set(a_cfg.keys()) | set(b_cfg.keys()))
        changed_cfg: list[str] = []
        for k in cfg_keys:
            if a_cfg.get(k) != b_cfg.get(k):
                changed_cfg.append(str(k))
                if len(changed_cfg) >= 50:
                    break

        def _delta_dict(da: object, db_: object, *, top: int = 20) -> dict[str, int]:
            ma = da if isinstance(da, dict) else {}
            mb = db_ if isinstance(db_, dict) else {}
            keys = {str(k) for k in ma.keys()} | {str(k) for k in mb.keys()}
            rows: list[tuple[str, int]] = []
            for k in keys:
                dv = _safe_int(mb.get(k), default=0) - _safe_int(ma.get(k), default=0)
                if dv:
                    rows.append((k, int(dv)))
            rows.sort(key=lambda kv: (-abs(kv[1]), kv[0]))
            out: dict[str, int] = {}
            for k, dv in rows[: max(0, int(top))]:
                out[str(k)[:64]] = int(dv)
            return out

        return {
            "changed_config_keys": changed_cfg,
            "status_count_delta": _delta_dict(a_stats.get("status_counts"), b_stats.get("status_counts")),
            "failure_reason_delta": _delta_dict(a_stats.get("failure_reasons_top"), b_stats.get("failure_reasons_top")),
            "pipeline_hash_docs_delta": _delta_dict(a_stats.get("pipeline_hash_docs"), b_stats.get("pipeline_hash_docs")),
        }
