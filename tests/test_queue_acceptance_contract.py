"""Queue acceptance against the installed ARQ enqueue/status implementation."""

import time
from unittest.mock import patch
from uuid import UUID

from arq.connections import ArqRedis
from arq.jobs import deserialize_job_raw
from redis.exceptions import ResponseError

from app.tasks import queue

TENANT = UUID(int=1)
DOCUMENT = UUID(int=2)


def _finish(coroutine):
    """All I/O in these tests is an immediate in-memory transport."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    finally:
        coroutine.close()
    raise AssertionError("The in-memory queue unexpectedly blocked")


class _Ready:
    def __init__(self, value):
        self.value = value

    def __await__(self):
        yield from ()
        return self.value


class _Pipeline:
    def __init__(self, broker):
        self.broker = broker
        self.watching = False
        self.commands = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def watch(self, key):
        self.watching = True

    def exists(self, *keys):
        if self.watching:
            return _Ready(any(key in self.broker.keys for key in keys))
        self.commands.append(("exists", keys))
        return self

    async def reset(self):
        self.commands.clear()

    def multi(self):
        return None

    def psetex(self, key, expires, payload):
        self.commands.append(("set", (key, payload)))

    def zadd(self, name, values):
        self.commands.append(("zadd", (name, values)))

    def zscore(self, name, job_id):
        self.commands.append(("zscore", (name, job_id)))
        return self

    async def execute(self):
        result = []
        for method, args in self.commands:
            if method == "exists":
                result.append(any(key in self.broker.keys for key in args))
            elif method == "zscore":
                result.append(self.broker.queued.get(args[1]))
            elif method == "set":
                self.broker.keys[args[0]] = args[1]
                self.broker.writes += 1
            elif method == "zadd":
                self.broker.queued.update(args[1])
        return result


class _Broker:
    default_queue_name = "mimirq"
    expires_extra_ms = 86400000
    job_serializer = None
    job_deserializer = None

    def __init__(self):
        self.keys = {}
        self.queued = {}
        self.writes = 0

    def pipeline(self, **kwargs):
        return _Pipeline(self)

    async def enqueue_job(self, *args, **kwargs):
        return await ArqRedis.enqueue_job(self, *args, **kwargs)


def _get_broker(broker):
    async def get():
        return broker

    return get


def test_document_retry_accepts_a_new_job_after_a_retained_result():
    broker = _Broker()
    job_id = "doc:tenant:document:pipeline"
    retained_result = b"completed result, including application failure"
    broker.keys[f"arq:result:{job_id}"] = retained_result
    with patch.object(queue, "get_queue", _get_broker(broker)):
        actual_id = _finish(
            queue.enqueue_document_processing(
                tenant_id=TENANT, document_id=DOCUMENT, requested_by="local", job_id=job_id
            )
        )
    assert actual_id.startswith(f"{job_id}:attempt:")
    assert actual_id in broker.queued
    assert f"arq:job:{actual_id}" in broker.keys
    assert broker.keys[f"arq:result:{job_id}"] == retained_result
    assert broker.writes == 1
    function, arguments, keywords, attempt, _enqueued_at = deserialize_job_raw(broker.keys[f"arq:job:{actual_id}"])
    assert (function, arguments, keywords, attempt) == (
        "process_document_job",
        (str(TENANT), str(DOCUMENT), "local"),
        {},
        1,
    )


def test_document_live_duplicates_reuse_the_real_accepted_job():
    broker = _Broker()
    with patch.object(queue, "get_queue", _get_broker(broker)):
        accepted = _finish(
            queue.enqueue_document_processing(
                tenant_id=TENANT, document_id=DOCUMENT, requested_by="local", job_id="doc:live"
            )
        )
        duplicate = _finish(
            queue.enqueue_document_processing(
                tenant_id=TENANT, document_id=DOCUMENT, requested_by="local", job_id="doc:live"
            )
        )
    assert accepted == duplicate == "doc:live"
    assert broker.writes == 1


def test_document_unknown_rejection_is_explicit():
    broker = _Broker()

    async def rejected(*args, **kwargs):
        return None

    broker.enqueue_job = rejected
    with patch.object(queue, "get_queue", _get_broker(broker)):
        try:
            _finish(
                queue.enqueue_document_processing(
                    tenant_id=TENANT, document_id=DOCUMENT, requested_by="local", job_id="doc:missing"
                )
            )
        except queue.TaskEnqueueRejectedError:
            pass
        else:
            raise AssertionError("An unknown rejected job must not be accepted")
    assert broker.writes == 0


def test_deferred_and_running_document_jobs_are_live_duplicates():
    for state in ("deferred", "in_progress"):
        broker = _Broker()
        broker.keys["arq:job:doc:live"] = b"existing payload"
        if state == "deferred":
            broker.queued["doc:live"] = int(time.time() * 1000) + 3600000
        else:
            broker.keys["arq:in-progress:doc:live"] = b"owned"
        with patch.object(queue, "get_queue", _get_broker(broker)):
            actual = _finish(
                queue.enqueue_document_processing(
                    tenant_id=TENANT, document_id=DOCUMENT, requested_by="local", job_id="doc:live"
                )
            )
        assert actual == "doc:live" and broker.writes == 0


def test_a_rejected_fresh_attempt_does_not_loop_or_report_acceptance():
    broker = _Broker()
    broker.keys["arq:result:doc:finished"] = b"retained"
    submitted = []

    async def submit(*args, **kwargs):
        submitted.append(kwargs["_job_id"])
        if len(submitted) == 1:
            return await ArqRedis.enqueue_job(broker, *args, **kwargs)
        return None

    broker.enqueue_job = submit
    with patch.object(queue, "get_queue", _get_broker(broker)):
        try:
            _finish(
                queue.enqueue_document_processing(
                    tenant_id=TENANT, document_id=DOCUMENT, requested_by="local", job_id="doc:finished"
                )
            )
        except queue.TaskEnqueueRejectedError:
            pass
        else:
            raise AssertionError("A rejected fresh attempt was accepted")
    assert len(submitted) == 2 and submitted[1].startswith("doc:finished:attempt:")
    assert broker.writes == 0


def _strict_submissions():
    common = {"tenant_id": TENANT, "requested_by": "local", "job_id": "strict:job"}
    return [
        (queue.enqueue_kg_extraction, {**common, "document_id": DOCUMENT}),
        (queue.enqueue_rebuild_indexes, common),
        (queue.enqueue_index_audit_reconcile_job, {**common, "dataset_id": DOCUMENT}),
        (queue.enqueue_dataset_profile_scan, {**common, "dataset_id": DOCUMENT, "scan_run_id": DOCUMENT}),
        (queue.enqueue_dataset_precheck_scan, {**common, "dataset_id": DOCUMENT, "scan_run_id": DOCUMENT}),
        (queue.enqueue_connector_run, {**common, "run_id": DOCUMENT}),
        (
            queue.enqueue_evidence_reference_sources_repair,
            {
                **common,
                "suite_id": DOCUMENT,
                "apply": False,
                "allow_approved": False,
                "include_archived_items": False,
                "max_items": 1,
                "max_refs_per_item": 1,
                "max_changes": 1,
            },
        ),
    ]


def test_all_strict_jobs_reuse_live_duplicates_and_reject_retained_results():
    for submit, arguments in _strict_submissions():
        broker = _Broker()
        with patch.object(queue, "get_queue", _get_broker(broker)):
            accepted = _finish(submit(**arguments))
            duplicate = _finish(submit(**arguments))
        assert accepted == duplicate == "strict:job"
        assert broker.writes == 1
        broker = _Broker()
        broker.keys["arq:result:strict:job"] = b"completed"
        with patch.object(queue, "get_queue", _get_broker(broker)):
            try:
                _finish(submit(**arguments))
            except queue.TaskEnqueueRejectedError:
                pass
            else:
                raise AssertionError(f"{submit.__name__} silently accepted a retained finished job")
        assert broker.writes == 0


def test_queue_disabled_preserves_none_without_importing_a_broker():
    async def disabled():
        return None

    with patch.object(queue, "get_queue", disabled):
        assert (
            _finish(queue.enqueue_document_processing(tenant_id=TENANT, document_id=DOCUMENT, requested_by="local"))
            is None
        )
        for submit, arguments in _strict_submissions():
            assert _finish(submit(**arguments)) is None


def test_force_retry_does_not_override_a_pending_live_handoff():
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.services.documents.processing import _ensure_retryable_document_state

    document = SimpleNamespace(
        status="pending", doc_metadata={"task_id": "accepted-live-job"}, current_stage="queued", processing_progress=0
    )
    try:
        _ensure_retryable_document_state(document=document, force=True)
    except HTTPException as error:
        assert error.status_code == 409
    else:
        raise AssertionError("force=True must not start another pending document attempt")


def test_a_full_non_evicting_broker_rejects_writes_visibly():
    broker = _Broker()
    failure = ResponseError("OOM command not allowed when used memory > maxmemory")

    class FullPipeline(_Pipeline):
        async def execute(self):
            raise failure

    broker.pipeline = lambda **kwargs: FullPipeline(broker)
    with patch.object(queue, "get_queue", _get_broker(broker)):
        try:
            _finish(
                queue.enqueue_document_processing(
                    tenant_id=TENANT, document_id=DOCUMENT, requested_by="local", job_id="doc:rejected"
                )
            )
        except ResponseError as error:
            assert error is failure
        else:
            raise AssertionError("A full non-evicting queue must not report a successful handoff")
    assert not broker.queued
