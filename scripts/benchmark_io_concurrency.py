#!/usr/bin/env python3
"""
I/O concurrency benchmark script.

Used to test and compare performance before/after optimizations:
- Batch document upload
- Image upload
- Embedding generation
- Vector indexing

Usage:
    python scripts/benchmark_io_concurrency.py --test all
    python scripts/benchmark_io_concurrency.py --test batch_upload
    python scripts/benchmark_io_concurrency.py --test embedding
"""

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path
from typing import Any

# Add project root to Python path.
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.factory import select_embedding_model


class BenchmarkResults:
    """Benchmark results."""

    def __init__(self, name: str):
        self.name = name
        self.times: list[float] = []

    def add_time(self, elapsed: float):
        """Add a single run time."""
        self.times.append(elapsed)

    def get_stats(self) -> dict[str, Any]:
        """Get summary stats."""
        if not self.times:
            return {"error": "No data"}

        return {
            "name": self.name,
            "count": len(self.times),
            "mean": statistics.mean(self.times),
            "median": statistics.median(self.times),
            "min": min(self.times),
            "max": max(self.times),
            "stdev": statistics.stdev(self.times) if len(self.times) > 1 else 0,
        }

    def print_stats(self):
        """Print summary stats."""
        stats = self.get_stats()
        if "error" in stats:
            print(f"❌ {self.name}: {stats['error']}")
            return

        print(f"\n{'=' * 60}")
        print(f"📊 {stats['name']}")
        print(f"{'=' * 60}")
        print(f"  Test runs: {stats['count']}")
        print(f"  Mean time: {stats['mean']:.2f}s")
        print(f"  Median:    {stats['median']:.2f}s")
        print(f"  Min:       {stats['min']:.2f}s")
        print(f"  Max:       {stats['max']:.2f}s")
        print(f"  Stdev:     {stats['stdev']:.2f}s")


async def benchmark_embedding_concurrent(
    model: BaseEmbeddingModel, num_texts: int = 1000, batch_size: int = 32, max_concurrent: int = 3, runs: int = 3
) -> BenchmarkResults:
    """
    Benchmark concurrent embedding generation performance.

    Args:
        model: Embedding model.
        num_texts: Number of texts.
        batch_size: Batch size.
        max_concurrent: Max concurrency.
        runs: Number of runs.
    """
    print(
        "\n🚀 Testing Embedding concurrent generation "
        f"(texts={num_texts}, batch={batch_size}, concurrent={max_concurrent})"
    )

    # Generate test data.
    texts = [f"This is test document number {i} for embedding benchmark." for i in range(num_texts)]

    results = BenchmarkResults(f"Embedding concurrent (concurrent={max_concurrent})")

    for run in range(runs):
        print(f"  Run {run + 1}/{runs}...", end=" ", flush=True)
        t0 = time.perf_counter()

        try:
            embeddings = await model.abatch_encode(texts, batch_size=batch_size, max_concurrent=max_concurrent)
            elapsed = time.perf_counter() - t0
            results.add_time(elapsed)
            print(f"✅ {elapsed:.2f}s ({len(embeddings)} embeddings)")
        except Exception as e:
            print(f"❌ Failed: {str(e)}")

    return results


async def benchmark_embedding_serial(
    model: BaseEmbeddingModel, num_texts: int = 1000, batch_size: int = 32, runs: int = 3
) -> BenchmarkResults:
    """
    Benchmark serial embedding generation performance (baseline).

    Args:
        model: Embedding model.
        num_texts: Number of texts.
        batch_size: Batch size.
        runs: Number of runs.
    """
    print(f"\n🐌 Testing Embedding serial generation (texts={num_texts}, batch={batch_size})")

    # Generate test data.
    texts = [f"This is test document number {i} for embedding benchmark." for i in range(num_texts)]

    results = BenchmarkResults("Embedding serial")

    for run in range(runs):
        print(f"  Run {run + 1}/{runs}...", end=" ", flush=True)
        t0 = time.perf_counter()

        try:
            embeddings = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                batch_embeddings = await model.aencode(batch)
                embeddings.extend(batch_embeddings)

            elapsed = time.perf_counter() - t0
            results.add_time(elapsed)
            print(f"✅ {elapsed:.2f}s ({len(embeddings)} embeddings)")
        except Exception as e:
            print(f"❌ Failed: {str(e)}")

    return results


async def benchmark_image_upload_concurrent(
    num_images: int = 20, max_concurrent: int = 10, runs: int = 3
) -> BenchmarkResults:
    """
    Benchmark concurrent image upload performance.

    Args:
        num_images: Number of images.
        max_concurrent: Max concurrency.
        runs: Number of runs.
    """
    print(f"\n🚀 Testing concurrent image upload (images={num_images}, concurrent={max_concurrent})")

    import uuid

    from app.storage.object.minio import minio_service

    # Generate test image data (simulate 1KB images).
    test_image_data = b"x" * 1024

    results = BenchmarkResults(f"Image upload concurrent (concurrent={max_concurrent})")

    for run in range(runs):
        print(f"  Run {run + 1}/{runs}...", end=" ", flush=True)

        # Prepare image payloads.
        images = [
            {
                "image_data": test_image_data,
                "tenant_id": "test-tenant",
                "dataset_id": str(uuid.uuid4()),
                "document_id": str(uuid.uuid4()),
                "chunk_key": f"test_{i}",
                "extension": "jpg",
            }
            for i in range(num_images)
        ]

        t0 = time.perf_counter()

        try:
            upload_results = await minio_service.upload_images_batch(images, max_concurrent=max_concurrent)
            elapsed = time.perf_counter() - t0
            success_count = sum(1 for r in upload_results if r.get("success"))
            results.add_time(elapsed)
            print(f"✅ {elapsed:.2f}s ({success_count}/{num_images} succeeded)")
        except Exception as e:
            print(f"❌ Failed: {str(e)}")

    return results


async def benchmark_image_upload_serial(num_images: int = 20, runs: int = 3) -> BenchmarkResults:
    """
    Benchmark serial image upload performance (baseline).

    Args:
        num_images: Number of images.
        runs: Number of runs.
    """
    print(f"\n🐌 Testing serial image upload (images={num_images})")

    import uuid

    from app.storage.object.minio import minio_service

    # Generate test image data (simulate 1KB images).
    test_image_data = b"x" * 1024

    results = BenchmarkResults("Image upload serial")

    for run in range(runs):
        print(f"  Run {run + 1}/{runs}...", end=" ", flush=True)

        t0 = time.perf_counter()

        try:
            success_count = 0
            for i in range(num_images):
                img_id = minio_service.upload_image(
                    image_data=test_image_data,
                    tenant_id="test-tenant",
                    dataset_id=str(uuid.uuid4()),
                    document_id=str(uuid.uuid4()),
                    chunk_key=f"test_{i}",
                    extension="jpg",
                )
                if img_id:
                    success_count += 1

            elapsed = time.perf_counter() - t0
            results.add_time(elapsed)
            print(f"✅ {elapsed:.2f}s ({success_count}/{num_images} succeeded)")
        except Exception as e:
            print(f"❌ Failed: {str(e)}")

    return results


def compare_results(baseline: BenchmarkResults, optimized: BenchmarkResults):
    """Compare pre- and post-optimization results."""
    baseline_stats = baseline.get_stats()
    optimized_stats = optimized.get_stats()

    if "error" in baseline_stats or "error" in optimized_stats:
        print("\n⚠️  Cannot compare: some tests failed")
        return

    improvement = (baseline_stats["mean"] - optimized_stats["mean"]) / baseline_stats["mean"] * 100
    speedup = baseline_stats["mean"] / optimized_stats["mean"]

    print(f"\n{'=' * 60}")
    print("📈 Performance Comparison")
    print(f"{'=' * 60}")
    print(f"  Pre-optimization mean: {baseline_stats['mean']:.2f}s")
    print(f"  Post-optimization mean: {optimized_stats['mean']:.2f}s")
    print(f"  Performance improvement: {improvement:.1f}%")
    print(f"  Speedup ratio: {speedup:.2f}x")

    if improvement > 0:
        print(f"  ✅ Performance improved by {improvement:.1f}%")
    else:
        print(f"  ⚠️  Performance degraded by {abs(improvement):.1f}%")


async def run_embedding_benchmark():
    """Run embedding benchmarks."""
    print("\n" + "=" * 60)
    print("🧪 Embedding Concurrency Performance Test")
    print("=" * 60)

    try:
        # Try configured embedding model.
        model_id = f"{settings.EMBEDDING_PROVIDER}/{settings.EMBEDDING_MODEL}"
        model = select_embedding_model(model_id)
        print(f"Using model: {model_id}")
    except Exception as e:
        print(f"⚠️  Failed to load embedding model: {e}")
        print("Skipping Embedding test")
        return

    # Serial baseline.
    serial_results = await benchmark_embedding_serial(
        model,
        num_texts=100,  # Reduced count for faster testing
        batch_size=32,
        runs=2,
    )
    serial_results.print_stats()

    # Concurrent run.
    concurrent_results = await benchmark_embedding_concurrent(
        model, num_texts=100, batch_size=32, max_concurrent=3, runs=2
    )
    concurrent_results.print_stats()

    # Compare.
    compare_results(serial_results, concurrent_results)


async def run_image_upload_benchmark():
    """Run image upload benchmarks."""
    print("\n" + "=" * 60)
    print("🧪 Image Upload Concurrency Performance Test")
    print("=" * 60)

    if not settings.MINIO_ENABLED:
        print("⚠️  MinIO not enabled, skipping image upload test")
        return

    # Serial baseline.
    serial_results = await benchmark_image_upload_serial(
        num_images=10,  # Reduced count for faster testing
        runs=2,
    )
    serial_results.print_stats()

    # Concurrent run.
    concurrent_results = await benchmark_image_upload_concurrent(num_images=10, max_concurrent=5, runs=2)
    concurrent_results.print_stats()

    # Compare.
    compare_results(serial_results, concurrent_results)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="I/O Concurrency Performance Benchmark")
    parser.add_argument(
        "--test", choices=["all", "embedding", "image_upload"], default="all", help="Select test to run"
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("🚀 MimirQ I/O Concurrency Performance Benchmark")
    print("=" * 60)

    if args.test in ["all", "embedding"]:
        await run_embedding_benchmark()

    if args.test in ["all", "image_upload"]:
        await run_image_upload_benchmark()

    print("\n" + "=" * 60)
    print("✅ Benchmark completed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
