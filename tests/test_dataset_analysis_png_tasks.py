import datetime as _dt
import json
import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import anyio
import pytest
import starlette.status as _status
from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1 import dataset_analysis as dataset_analysis_api
from app.core.database import get_db
from app.core.exceptions import register_exception_handlers
from app.rag.evaluation.poc_runner import png_tasks
from app.services import dataset_analysis_service

if not hasattr(_dt, "UTC"):
    _dt.UTC = _dt.timezone.utc
if not hasattr(_status, "HTTP_413_CONTENT_TOO_LARGE"):
    _status.HTTP_413_CONTENT_TOO_LARGE = _status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
if not hasattr(_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    _status.HTTP_422_UNPROCESSABLE_CONTENT = _status.HTTP_422_UNPROCESSABLE_ENTITY
UTC = _dt.UTC


class _FakeRedis:
    def __init__(self):
        self._values: dict[str, bytes] = {}
        self._expires_at: dict[str, datetime] = {}
        self.now = datetime.now(UTC)

    def advance(self, *, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)

    def _purge_if_expired(self, key: str) -> None:
        expires_at = self._expires_at.get(key)
        if expires_at is not None and expires_at <= self.now:
            self._values.pop(key, None)
            self._expires_at.pop(key, None)

    def set(self, key, value, ex=None, nx=False):
        self._purge_if_expired(key)
        if nx and key in self._values:
            return False
        raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
        self._values[str(key)] = raw
        if ex is not None:
            self._expires_at[str(key)] = self.now + timedelta(seconds=int(ex))
        else:
            self._expires_at.pop(str(key), None)
        return True

    def get(self, key):
        self._purge_if_expired(str(key))
        return self._values.get(str(key))

    def delete(self, key):
        existed = str(key) in self._values
        self._values.pop(str(key), None)
        self._expires_at.pop(str(key), None)
        return 1 if existed else 0

    def eval(self, script, numkeys, *args):
        assert numkeys == 1
        key = str(args[0])
        argv = args[1:]
        self._purge_if_expired(key)
        current = self._values.get(key)

        if "DEL" in script and "ARGV[1]" in script and "GET" in script:
            if current == str(argv[0]).encode("utf-8"):
                return self.delete(key)
            return 0

        if "EXPIRE" in script and "ARGV[2]" in script and "GET" in script:
            if current == str(argv[0]).encode("utf-8"):
                self._expires_at[key] = self.now + timedelta(seconds=int(argv[1]))
                return 1
            return 0

        if "SET" in script and "ARGV[2]" in script:
            expected = argv[0]
            replacement = argv[1]
            ttl_sec = int(argv[2])
            if current != expected:
                return 0
            self._values[key] = replacement if isinstance(replacement, bytes) else str(replacement).encode("utf-8")
            self._expires_at[key] = self.now + timedelta(seconds=ttl_sec)
            return 1

        raise AssertionError(f"Unsupported eval script: {script}")


def _install_fake_redis(monkeypatch: pytest.MonkeyPatch, redis: _FakeRedis) -> None:
    monkeypatch.setattr(png_tasks, "_get_redis_client", lambda: redis, raising=True)
    monkeypatch.setattr(png_tasks, "_invalidate_redis_client", lambda: None, raising=True)
    monkeypatch.setattr(png_tasks, "_utc_now", lambda: redis.now, raising=True)
    monkeypatch.setattr(dataset_analysis_service, "get_png_export_task", png_tasks.get_png_export_task, raising=True)
    monkeypatch.setattr(
        dataset_analysis_service, "get_png_export_task_result", png_tasks.get_png_export_task_result, raising=True
    )
    monkeypatch.setattr(
        dataset_analysis_service, "create_png_export_task", png_tasks.create_png_export_task, raising=True
    )
    monkeypatch.setattr(
        dataset_analysis_service, "begin_png_export_task", png_tasks.begin_png_export_task, raising=True
    )
    monkeypatch.setattr(
        dataset_analysis_service, "heartbeat_png_export_task", png_tasks.heartbeat_png_export_task, raising=True
    )
    monkeypatch.setattr(
        dataset_analysis_service,
        "get_png_export_task_heartbeat_interval_sec",
        png_tasks.get_png_export_task_heartbeat_interval_sec,
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_service, "complete_png_export_task", png_tasks.complete_png_export_task, raising=True
    )
    monkeypatch.setattr(dataset_analysis_service, "fail_png_export_task", png_tasks.fail_png_export_task, raising=True)


def _read_task_record(redis: _FakeRedis, task_id: str) -> dict[str, object]:
    for key, raw in redis._values.items():
        if task_id in key and ":task:" in key:
            return json.loads(raw)
    raise KeyError(task_id)


def test_create_task_fails_closed_without_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(png_tasks, "_get_redis_client", lambda: None, raising=True)
    monkeypatch.setattr(png_tasks, "_invalidate_redis_client", lambda: None, raising=True)

    with pytest.raises(RuntimeError, match="Redis"):
        png_tasks.create_png_export_task(
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            filters={},
            requested_by="reader-1",
            account_id="reader-1",
        )


def test_task_scope_binding_and_result_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    _install_fake_redis(monkeypatch, redis)

    task = png_tasks.create_png_export_task(
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        filters={"k": "v"},
        requested_by="reader-1",
        account_id="reader-1",
    )
    started = png_tasks.begin_png_export_task(task["task_id"], tenant_id="tenant-1", dataset_id="dataset-1")
    png_tasks.complete_png_export_task(
        task["task_id"],
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        owner_token=str(started["owner_token"]),
        png_bytes=b"png-bytes",
    )

    status = png_tasks.get_png_export_task(
        task["task_id"],
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        account_id="reader-1",
    )

    assert status["status"] == "done"
    assert _read_task_record(redis, task["task_id"])["requested_by"] == "reader-1"
    assert _read_task_record(redis, task["task_id"])["account_id"] == "reader-1"
    assert (
        png_tasks.get_png_export_task_result(
            task["task_id"],
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            account_id="reader-1",
        )
        == b"png-bytes"
    )
    with pytest.raises(KeyError):
        png_tasks.get_png_export_task(
            task["task_id"],
            tenant_id="tenant-2",
            dataset_id="dataset-1",
            account_id="reader-1",
        )
    with pytest.raises(KeyError):
        png_tasks.get_png_export_task_result(
            task["task_id"],
            tenant_id="tenant-1",
            dataset_id="dataset-2",
            account_id="reader-1",
        )
    with pytest.raises(KeyError):
        png_tasks.get_png_export_task(
            task["task_id"],
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            account_id="reader-2",
        )
    with pytest.raises(KeyError):
        png_tasks.get_png_export_task_result(
            task["task_id"],
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            account_id="reader-2",
        )


def test_legacy_task_payload_without_owner_binding_fails_closed_for_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    _install_fake_redis(monkeypatch, redis)

    task = png_tasks.create_png_export_task(
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        filters={},
        requested_by="reader-1",
        account_id="reader-1",
    )
    task_key = png_tasks._task_key(task["task_id"])
    stored = json.loads(redis.get(task_key))
    stored.pop("account_id", None)
    stored.pop("requested_by", None)
    redis.set(task_key, json.dumps(stored).encode("utf-8"), ex=600)

    started = png_tasks.begin_png_export_task(task["task_id"], tenant_id="tenant-1", dataset_id="dataset-1")
    png_tasks.complete_png_export_task(
        task["task_id"],
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        owner_token=str(started["owner_token"]),
        png_bytes=b"png-bytes",
    )

    with pytest.raises(KeyError):
        png_tasks.get_png_export_task(
            task["task_id"],
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            account_id="reader-1",
        )
    with pytest.raises(KeyError):
        png_tasks.get_png_export_task_result(
            task["task_id"],
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            account_id="reader-1",
        )


def test_oversized_result_marks_task_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    monkeypatch.setattr(png_tasks.settings, "DATASET_ANALYSIS_PNG_RESULT_MAX_BYTES", 4, raising=False)

    task = png_tasks.create_png_export_task(
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        filters={},
        requested_by="reader-1",
        account_id="reader-1",
    )
    started = png_tasks.begin_png_export_task(task["task_id"], tenant_id="tenant-1", dataset_id="dataset-1")
    png_tasks.complete_png_export_task(
        task["task_id"],
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        owner_token=str(started["owner_token"]),
        png_bytes=b"too-large",
    )

    status = png_tasks.get_png_export_task(
        task["task_id"],
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        account_id="reader-1",
    )

    assert status["status"] == "failed"
    assert status["error_code"] == "result_too_large"
    with pytest.raises(KeyError):
        png_tasks.get_png_export_task_result(
            task["task_id"],
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            account_id="reader-1",
        )


def test_stale_running_becomes_worker_lost_and_late_completion_cannot_revive(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    monkeypatch.setattr(png_tasks.settings, "DATASET_ANALYSIS_PNG_STALE_AFTER_SEC", 5, raising=False)

    task = png_tasks.create_png_export_task(
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        filters={},
        requested_by="reader-1",
        account_id="reader-1",
    )
    started = png_tasks.begin_png_export_task(task["task_id"], tenant_id="tenant-1", dataset_id="dataset-1")
    redis.advance(seconds=10)

    failed = png_tasks.get_png_export_task(
        task["task_id"],
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        account_id="reader-1",
    )
    png_tasks.complete_png_export_task(
        task["task_id"],
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        owner_token=str(started["owner_token"]),
        png_bytes=b"late",
    )

    assert failed["status"] == "failed"
    assert failed["error_code"] == "worker_lost"
    assert (
        png_tasks.get_png_export_task(
            task["task_id"],
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            account_id="reader-1",
        )["status"]
        == "failed"
    )
    with pytest.raises(KeyError):
        png_tasks.get_png_export_task_result(
            task["task_id"],
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            account_id="reader-1",
        )


def test_heartbeat_owner_mismatch_does_not_update(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    monkeypatch.setattr(png_tasks.settings, "DATASET_ANALYSIS_PNG_STALE_AFTER_SEC", 6, raising=False)

    task = png_tasks.create_png_export_task(
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        filters={},
        requested_by="reader-1",
        account_id="reader-1",
    )
    started = png_tasks.begin_png_export_task(task["task_id"], tenant_id="tenant-1", dataset_id="dataset-1")
    before = _read_task_record(redis, task["task_id"])
    redis.advance(seconds=1)

    renewed = png_tasks.heartbeat_png_export_task(
        task["task_id"],
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        owner_token=f"{started['owner_token']}-wrong",
    )
    after = _read_task_record(redis, task["task_id"])

    assert renewed is False
    assert after["updated_at"] == before["updated_at"]
    assert after["lease_expires_at"] == before["lease_expires_at"]


def test_running_task_only_becomes_worker_lost_after_heartbeat_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    monkeypatch.setattr(png_tasks.settings, "DATASET_ANALYSIS_PNG_STALE_AFTER_SEC", 6, raising=False)

    task = png_tasks.create_png_export_task(
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        filters={},
        requested_by="reader-1",
        account_id="reader-1",
    )
    started = png_tasks.begin_png_export_task(task["task_id"], tenant_id="tenant-1", dataset_id="dataset-1")

    for _ in range(3):
        redis.advance(seconds=2)
        assert (
            png_tasks.heartbeat_png_export_task(
                task["task_id"],
                tenant_id="tenant-1",
                dataset_id="dataset-1",
                owner_token=str(started["owner_token"]),
            )
            is True
        )
        assert (
            png_tasks.get_png_export_task(
                task["task_id"],
                tenant_id="tenant-1",
                dataset_id="dataset-1",
                account_id="reader-1",
            )["status"]
            == "running"
        )

    redis.advance(seconds=7)
    failed = png_tasks.get_png_export_task(
        task["task_id"],
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        account_id="reader-1",
    )

    assert failed["status"] == "failed"
    assert failed["error_code"] == "worker_lost"


def test_terminal_retention_expires_status_and_result(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    monkeypatch.setattr(png_tasks.settings, "DATASET_ANALYSIS_PNG_TERMINAL_TTL_SEC", 2, raising=False)

    task = png_tasks.create_png_export_task(
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        filters={},
        requested_by="reader-1",
        account_id="reader-1",
    )
    started = png_tasks.begin_png_export_task(task["task_id"], tenant_id="tenant-1", dataset_id="dataset-1")
    png_tasks.complete_png_export_task(
        task["task_id"],
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        owner_token=str(started["owner_token"]),
        png_bytes=b"ok",
    )
    redis.advance(seconds=3)

    with pytest.raises(KeyError):
        png_tasks.get_png_export_task(
            task["task_id"],
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            account_id="reader-1",
        )
    with pytest.raises(KeyError):
        png_tasks.get_png_export_task_result(
            task["task_id"],
            tenant_id="tenant-1",
            dataset_id="dataset-1",
            account_id="reader-1",
        )


def test_png_background_task_marks_source_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    _install_fake_redis(monkeypatch, redis)

    monkeypatch.setattr(
        dataset_analysis_service,
        "_build_full_bundle",
        lambda **_k: (_ for _ in ()).throw(
            dataset_analysis_service.DatasetAnalysisSourceIncompleteError(dataset_id="dataset-1")
        ),
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_service, "SessionLocal", lambda: SimpleNamespace(close=lambda: None), raising=True
    )

    background_tasks = BackgroundTasks()
    task = dataset_analysis_service.create_dataset_analysis_png_task(
        db=object(),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        dataset_name="Dataset A",
        account_id="reader-1",
        background_tasks=background_tasks,
    )

    assert len(background_tasks.tasks) == 1
    anyio.run(background_tasks.tasks[0])
    status = png_tasks.get_png_export_task(
        task["task_id"],
        tenant_id=task["tenant_id"],
        dataset_id=task["dataset_id"],
        account_id="reader-1",
    )

    assert status["status"] == "failed"
    assert status["error_code"] == "source_incomplete"


def test_png_background_task_heartbeats_across_multiple_stale_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    _install_fake_redis(monkeypatch, redis)
    monkeypatch.setattr(png_tasks.settings, "DATASET_ANALYSIS_PNG_STALE_AFTER_SEC", 5, raising=False)
    monkeypatch.setattr(
        dataset_analysis_service, "SessionLocal", lambda: SimpleNamespace(close=lambda: None), raising=True
    )
    monkeypatch.setattr(
        dataset_analysis_service,
        "_build_full_bundle",
        lambda **_k: {
            "meta": {"filters": {}, "scope_summary": {}, "definitions": {}},
            "metrics": {},
            "counts": {},
            "ratios": {},
            "top_examples": {},
            "manual_review_candidates": [],
            "glossary_candidates": [],
            "keyword_scores": [],
            "coverage_heatmap": {},
            "umap_scatter": {},
            "latency_breakdown": {},
        },
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_service,
        "build_dataset_analysis_report",
        lambda payload: {"meta": {}, "payload": payload.dataset_id},
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_service, "get_png_export_task_heartbeat_interval_sec", lambda: 0.01, raising=True
    )

    render_entered = threading.Event()
    allow_finish = threading.Event()

    def _render(_report):
        render_entered.set()
        for _ in range(3):
            redis.advance(seconds=4)
            time.sleep(0.03)
        allow_finish.wait(timeout=1.0)
        return b"png-bytes"

    monkeypatch.setattr(dataset_analysis_service, "render_dataset_analysis_png", _render, raising=True)

    background_tasks = BackgroundTasks()
    task = dataset_analysis_service.create_dataset_analysis_png_task(
        db=object(),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        dataset_name="Dataset A",
        account_id="reader-1",
        background_tasks=background_tasks,
    )

    worker = threading.Thread(target=lambda: anyio.run(background_tasks.tasks[0]), daemon=True)
    worker.start()
    assert render_entered.wait(timeout=1.0)

    status = png_tasks.get_png_export_task(
        task["task_id"],
        tenant_id=task["tenant_id"],
        dataset_id=task["dataset_id"],
        account_id="reader-1",
    )
    allow_finish.set()
    worker.join(timeout=1.0)

    assert status["status"] == "running"
    final = png_tasks.get_png_export_task(
        task["task_id"],
        tenant_id=task["tenant_id"],
        dataset_id=task["dataset_id"],
        account_id="reader-1",
    )
    assert final["status"] == "done"


def test_png_export_endpoint_returns_non_202_when_shared_state_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = str(uuid4())
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(dataset_analysis_api.router, prefix="/api/v1/datasets")
    app.dependency_overrides[get_tenant_id] = lambda: str(uuid4())
    app.dependency_overrides[get_current_account_id] = lambda: "reader-1"
    app.dependency_overrides[get_db] = lambda: object()

    monkeypatch.setattr(dataset_analysis_api.DatasetService, "ensure_member", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(
        dataset_analysis_api.DatasetService,
        "get_dataset",
        lambda *_a, **_k: SimpleNamespace(id=dataset_id, name="Dataset A"),
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True
    )
    monkeypatch.setattr(
        dataset_analysis_api,
        "create_dataset_analysis_png_task",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("Redis unavailable")),
        raising=True,
    )

    response = TestClient(app).post(f"/api/v1/datasets/{dataset_id}/analysis/export.png")

    assert response.status_code == 503
