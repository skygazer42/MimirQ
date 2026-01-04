#!/usr/bin/env python3
"""
Arq 队列端到端基准测试（需要 Redis + worker 正在运行）。

用法：
  python scripts/benchmark_queue_e2e.py --n 50 --concurrency 10

前置：
  - docker compose up -d redis worker
  - 或本地启动：
      export TASK_QUEUE_ENABLED=true
      export REDIS_URL=redis://localhost:6379/0
      arq app.tasks.worker.WorkerSettings
"""

import argparse
import asyncio
import statistics
import time

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import settings


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=50, help="总请求数")
    parser.add_argument("--concurrency", type=int, default=10, help="并发数")
    parser.add_argument("--timeout", type=float, default=10.0, help="等待结果超时（秒）")
    args = parser.parse_args()

    pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))

    sem = asyncio.Semaphore(args.concurrency)
    latencies = []

    async def one(i: int):
        async with sem:
            t0 = time.perf_counter()
            job = await pool.enqueue_job("ping_job", _queue_name=getattr(settings, "TASK_QUEUE_NAME", "mimirq"))
            # arq job.result() 在 worker 完成后返回
            await job.result(timeout=args.timeout)
            latencies.append(time.perf_counter() - t0)

    await asyncio.gather(*[one(i) for i in range(args.n)])
    await pool.close()

    latencies.sort()
    mean = statistics.mean(latencies)
    p95 = latencies[int(0.95 * (len(latencies) - 1))]
    print(f"count={len(latencies)} mean={mean*1000:.1f}ms p95={p95*1000:.1f}ms min={latencies[0]*1000:.1f}ms max={latencies[-1]*1000:.1f}ms")


if __name__ == "__main__":
    asyncio.run(main())


