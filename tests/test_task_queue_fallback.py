from __future__ import annotations

import pytest
from uuid import UUID


@pytest.mark.asyncio
async def test_enqueue_returns_none_when_disabled(monkeypatch):
    from app.core import config as config_mod
    from app.tasks.queue import enqueue_document_processing

    # 强制关闭队列（保持 API 兼容的 fallback 场景）
    monkeypatch.setattr(config_mod.settings, "TASK_QUEUE_ENABLED", False, raising=False)

    task_id = await enqueue_document_processing(
        tenant_id=UUID("00000000-0000-0000-0000-000000000000"),
        document_id=UUID("00000000-0000-0000-0000-000000000000"),
        requested_by="test",
        job_id="doc:test",
    )
    assert task_id is None


