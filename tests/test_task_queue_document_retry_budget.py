from __future__ import annotations


def test_document_queue_retry_budget_exceeds_generic_jitter_budget():
    from app.core.config import settings

    assert settings.TASK_JOB_MAX_TRIES == 3
    assert settings.TASK_DOCUMENT_JOB_MAX_TRIES > settings.TASK_JOB_MAX_TRIES
    assert settings.TASK_DOCUMENT_RETRY_DEFER_SEC >= 10
    assert settings.TASK_KG_JOB_MAX_TRIES > settings.TASK_JOB_MAX_TRIES
    assert settings.TASK_KG_RETRY_DEFER_SEC >= 10


def test_worker_assigns_document_jobs_a_dedicated_retry_budget():
    from app.core.config import settings
    from app.tasks.worker import WorkerSettings

    document_functions = [
        fn
        for fn in WorkerSettings.functions
        if getattr(fn, "name", "") == "process_document_job"
    ]

    assert len(document_functions) == 1
    assert document_functions[0].max_tries == settings.TASK_DOCUMENT_JOB_MAX_TRIES


def test_worker_assigns_kg_jobs_a_dedicated_retry_budget():
    from app.core.config import settings
    from app.tasks.worker import WorkerSettings

    kg_functions = [
        fn
        for fn in WorkerSettings.functions
        if getattr(fn, "name", "") == "extract_kg_job"
    ]

    assert len(kg_functions) == 1
    assert kg_functions[0].max_tries == settings.TASK_KG_JOB_MAX_TRIES
