import asyncio
import time
from uuid import uuid4

import pytest

from app.parsing.subprocess_runner import SubprocessCancelled, run_subprocess_worker
from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_run_subprocess_worker_can_be_cancelled_via_cancel_check():
    tenant_id = uuid4()
    start = time.monotonic()

    async def cancel_check() -> bool:
        await yield_control()
        return (time.monotonic() - start) > 0.5

    with pytest.raises(SubprocessCancelled):
        await asyncio.wait_for(
            run_subprocess_worker(
                tenant_id=tenant_id,
                payload={"action": "sleep", "tenant_id": str(tenant_id), "duration_sec": 10},
                cancel_check=cancel_check,
                timeout_sec=30,
                poll_interval_sec=0.05,
            ),
            timeout=20,
        )
