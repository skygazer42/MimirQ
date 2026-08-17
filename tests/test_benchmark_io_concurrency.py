import asyncio
import sys

import pytest

from app.storage.object import minio as minio_module
from scripts import benchmark_io_concurrency as benchmark_module


def test_benchmark_results_reports_expected_summary() -> None:
    results = benchmark_module.BenchmarkResults("sample")
    assert results.get_stats() == {"error": "No data"}

    results.add_time(1.0)
    results.add_time(3.0)
    stats = results.get_stats()

    assert stats["name"] == "sample"
    assert stats["count"] == 2
    assert stats["mean"] == pytest.approx(2.0)
    assert stats["median"] == pytest.approx(2.0)
    assert stats["min"] == pytest.approx(1.0)
    assert stats["max"] == pytest.approx(3.0)
    assert stats["stdev"] == pytest.approx(1.4142135623730951)


def test_benchmark_embedding_serial_processes_batches(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.batches: list[list[str]] = []

        async def aencode(self, batch: list[str]) -> list[list[int]]:
            self.batches.append(list(batch))
            return [[len(text)] for text in batch]

    model = FakeModel()
    results = asyncio.run(benchmark_module.benchmark_embedding_serial(model, num_texts=5, batch_size=2, runs=1))

    assert [len(batch) for batch in model.batches] == [2, 2, 1]
    assert len(results.times) == 1
    assert "5 embeddings" in capsys.readouterr().out


def test_benchmark_embedding_concurrent_passes_batch_and_concurrency(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def abatch_encode(
            self,
            texts: list[str],
            *,
            batch_size: int,
            max_concurrent: int,
        ) -> list[list[int]]:
            self.calls.append(
                {
                    "count": len(texts),
                    "batch_size": batch_size,
                    "max_concurrent": max_concurrent,
                }
            )
            return [[index] for index, _ in enumerate(texts)]

    model = FakeModel()
    results = asyncio.run(
        benchmark_module.benchmark_embedding_concurrent(
            model,
            num_texts=4,
            batch_size=2,
            max_concurrent=7,
            runs=1,
        )
    )

    assert model.calls == [
        {"count": 4, "batch_size": 2, "max_concurrent": 7},
    ]
    assert len(results.times) == 1
    assert "4 embeddings" in capsys.readouterr().out


def test_benchmark_image_upload_helpers_preserve_upload_shapes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeMinioService:
        def __init__(self) -> None:
            self.serial_calls: list[dict[str, object]] = []
            self.batch_calls: list[tuple[list[dict[str, object]], int]] = []

        def upload_image(self, **kwargs: object) -> str:
            self.serial_calls.append(kwargs)
            return f"image-{len(self.serial_calls)}"

        async def upload_images_batch(
            self,
            images: list[dict[str, object]],
            *,
            max_concurrent: int,
        ) -> list[dict[str, bool]]:
            self.batch_calls.append((images, max_concurrent))
            return [{"success": True} for _ in images]

    minio_service = FakeMinioService()
    monkeypatch.setattr(minio_module, "minio_service", minio_service)

    serial_results = asyncio.run(benchmark_module.benchmark_image_upload_serial(num_images=3, runs=1))
    concurrent_results = asyncio.run(
        benchmark_module.benchmark_image_upload_concurrent(num_images=4, max_concurrent=5, runs=1)
    )

    assert len(serial_results.times) == 1
    assert len(concurrent_results.times) == 1
    assert len(minio_service.serial_calls) == 3
    assert len(minio_service.batch_calls) == 1
    images, max_concurrent = minio_service.batch_calls[0]
    assert len(images) == 4
    assert max_concurrent == 5

    output = capsys.readouterr().out
    assert "3/3 succeeded" in output
    assert "4/4 succeeded" in output


def test_run_embedding_benchmark_skips_on_model_load_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _raise(_model_id: str) -> object:
        raise RuntimeError("load failed")

    monkeypatch.setattr(benchmark_module, "select_embedding_model", _raise)

    asyncio.run(benchmark_module.run_embedding_benchmark())

    output = capsys.readouterr().out
    assert "Failed to load embedding model" in output
    assert "Skipping Embedding test" in output


@pytest.mark.parametrize(
    ("argv", "expected_calls"),
    [
        (["benchmark_io_concurrency.py"], ["embedding", "image"]),
        (["benchmark_io_concurrency.py", "--test", "embedding"], ["embedding"]),
        (["benchmark_io_concurrency.py", "--test", "image_upload"], ["image"]),
    ],
)
def test_main_dispatches_requested_benchmarks(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    expected_calls: list[str],
) -> None:
    calls: list[str] = []

    async def _run_embedding() -> None:
        calls.append("embedding")

    async def _run_image_upload() -> None:
        calls.append("image")

    monkeypatch.setattr(benchmark_module, "run_embedding_benchmark", _run_embedding)
    monkeypatch.setattr(benchmark_module, "run_image_upload_benchmark", _run_image_upload)
    monkeypatch.setattr(sys, "argv", argv)

    asyncio.run(benchmark_module.main())

    assert calls == expected_calls
