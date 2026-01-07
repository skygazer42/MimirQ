#!/usr/bin/env python3
"""
I/O 并发性能基准测试脚本

用于测试和对比优化前后的性能指标：
- 批量文档上传
- 图片上传
- Embedding 生成
- 向量索引

使用方法:
    python script/benchmark_io_concurrency.py --test all
    python script/benchmark_io_concurrency.py --test batch_upload
    python script/benchmark_io_concurrency.py --test embedding
"""
import argparse
import asyncio
import time
import sys
from pathlib import Path
from typing import List, Dict, Any
import statistics

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.factory import select_embedding_model
from app.core.config import settings


class BenchmarkResults:
    """基准测试结果"""
    
    def __init__(self, name: str):
        self.name = name
        self.times: List[float] = []
    
    def add_time(self, elapsed: float):
        """添加一次测试时间"""
        self.times.append(elapsed)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
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
        """打印统计信息"""
        stats = self.get_stats()
        if "error" in stats:
            print(f"❌ {self.name}: {stats['error']}")
            return
        
        print(f"\n{'='*60}")
        print(f"📊 {stats['name']}")
        print(f"{'='*60}")
        print(f"  测试次数: {stats['count']}")
        print(f"  平均耗时: {stats['mean']:.2f}s")
        print(f"  中位数:   {stats['median']:.2f}s")
        print(f"  最小值:   {stats['min']:.2f}s")
        print(f"  最大值:   {stats['max']:.2f}s")
        print(f"  标准差:   {stats['stdev']:.2f}s")


async def benchmark_embedding_concurrent(
    model: BaseEmbeddingModel,
    num_texts: int = 1000,
    batch_size: int = 32,
    max_concurrent: int = 3,
    runs: int = 3
) -> BenchmarkResults:
    """
    测试 Embedding 并发生成性能
    
    Args:
        model: Embedding 模型
        num_texts: 文本数量
        batch_size: 批次大小
        max_concurrent: 最大并发数
        runs: 测试运行次数
    """
    print(f"\n🚀 测试 Embedding 并发生成 (texts={num_texts}, batch={batch_size}, concurrent={max_concurrent})")
    
    # 生成测试数据
    texts = [f"This is test document number {i} for embedding benchmark." for i in range(num_texts)]
    
    results = BenchmarkResults(f"Embedding 并发 (concurrent={max_concurrent})")
    
    for run in range(runs):
        print(f"  运行 {run + 1}/{runs}...", end=" ", flush=True)
        t0 = time.perf_counter()
        
        try:
            embeddings = await model.abatch_encode(
                texts,
                batch_size=batch_size,
                max_concurrent=max_concurrent
            )
            elapsed = time.perf_counter() - t0
            results.add_time(elapsed)
            print(f"✅ {elapsed:.2f}s ({len(embeddings)} embeddings)")
        except Exception as e:
            print(f"❌ 失败: {str(e)}")
    
    return results


async def benchmark_embedding_serial(
    model: BaseEmbeddingModel,
    num_texts: int = 1000,
    batch_size: int = 32,
    runs: int = 3
) -> BenchmarkResults:
    """
    测试 Embedding 串行生成性能（对比基准）
    
    Args:
        model: Embedding 模型
        num_texts: 文本数量
        batch_size: 批次大小
        runs: 测试运行次数
    """
    print(f"\n🐌 测试 Embedding 串行生成 (texts={num_texts}, batch={batch_size})")
    
    # 生成测试数据
    texts = [f"This is test document number {i} for embedding benchmark." for i in range(num_texts)]
    
    results = BenchmarkResults("Embedding 串行")
    
    for run in range(runs):
        print(f"  运行 {run + 1}/{runs}...", end=" ", flush=True)
        t0 = time.perf_counter()
        
        try:
            embeddings = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i+batch_size]
                batch_embeddings = await model.aencode(batch)
                embeddings.extend(batch_embeddings)
            
            elapsed = time.perf_counter() - t0
            results.add_time(elapsed)
            print(f"✅ {elapsed:.2f}s ({len(embeddings)} embeddings)")
        except Exception as e:
            print(f"❌ 失败: {str(e)}")
    
    return results


async def benchmark_image_upload_concurrent(
    num_images: int = 20,
    max_concurrent: int = 10,
    runs: int = 3
) -> BenchmarkResults:
    """
    测试图片并发上传性能
    
    Args:
        num_images: 图片数量
        max_concurrent: 最大并发数
        runs: 测试运行次数
    """
    print(f"\n🚀 测试图片并发上传 (images={num_images}, concurrent={max_concurrent})")
    
    from app.storage.object.minio import minio_service
    import uuid
    
    # 生成测试图片数据（模拟 1KB 图片）
    test_image_data = b"x" * 1024
    
    results = BenchmarkResults(f"图片上传并发 (concurrent={max_concurrent})")
    
    for run in range(runs):
        print(f"  运行 {run + 1}/{runs}...", end=" ", flush=True)
        
        # 准备图片数据
        images = [
            {
                "image_data": test_image_data,
                "tenant_id": "test-tenant",
                "dataset_id": str(uuid.uuid4()),
                "document_id": str(uuid.uuid4()),
                "chunk_key": f"test_{i}",
                "extension": "jpg"
            }
            for i in range(num_images)
        ]
        
        t0 = time.perf_counter()
        
        try:
            upload_results = await minio_service.upload_images_batch(
                images,
                max_concurrent=max_concurrent
            )
            elapsed = time.perf_counter() - t0
            success_count = sum(1 for r in upload_results if r.get("success"))
            results.add_time(elapsed)
            print(f"✅ {elapsed:.2f}s ({success_count}/{num_images} 成功)")
        except Exception as e:
            print(f"❌ 失败: {str(e)}")
    
    return results


async def benchmark_image_upload_serial(
    num_images: int = 20,
    runs: int = 3
) -> BenchmarkResults:
    """
    测试图片串行上传性能（对比基准）
    
    Args:
        num_images: 图片数量
        runs: 测试运行次数
    """
    print(f"\n🐌 测试图片串行上传 (images={num_images})")
    
    from app.storage.object.minio import minio_service
    import uuid
    
    # 生成测试图片数据（模拟 1KB 图片）
    test_image_data = b"x" * 1024
    
    results = BenchmarkResults("图片上传串行")
    
    for run in range(runs):
        print(f"  运行 {run + 1}/{runs}...", end=" ", flush=True)
        
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
                    extension="jpg"
                )
                if img_id:
                    success_count += 1
            
            elapsed = time.perf_counter() - t0
            results.add_time(elapsed)
            print(f"✅ {elapsed:.2f}s ({success_count}/{num_images} 成功)")
        except Exception as e:
            print(f"❌ 失败: {str(e)}")
    
    return results


def compare_results(baseline: BenchmarkResults, optimized: BenchmarkResults):
    """对比优化前后的结果"""
    baseline_stats = baseline.get_stats()
    optimized_stats = optimized.get_stats()
    
    if "error" in baseline_stats or "error" in optimized_stats:
        print("\n⚠️  无法对比：部分测试失败")
        return
    
    improvement = (baseline_stats["mean"] - optimized_stats["mean"]) / baseline_stats["mean"] * 100
    speedup = baseline_stats["mean"] / optimized_stats["mean"]
    
    print(f"\n{'='*60}")
    print("📈 性能对比")
    print(f"{'='*60}")
    print(f"  优化前平均: {baseline_stats['mean']:.2f}s")
    print(f"  优化后平均: {optimized_stats['mean']:.2f}s")
    print(f"  性能提升:   {improvement:.1f}%")
    print(f"  加速比:     {speedup:.2f}x")
    
    if improvement > 0:
        print(f"  ✅ 性能提升 {improvement:.1f}%")
    else:
        print(f"  ⚠️  性能下降 {abs(improvement):.1f}%")


async def run_embedding_benchmark():
    """运行 Embedding 基准测试"""
    print("\n" + "="*60)
    print("🧪 Embedding 并发性能测试")
    print("="*60)
    
    try:
        # 尝试使用配置的 embedding 模型
        model_id = f"{settings.EMBEDDING_PROVIDER}/{settings.EMBEDDING_MODEL}"
        model = select_embedding_model(model_id)
        print(f"使用模型: {model_id}")
    except Exception as e:
        print(f"⚠️  无法加载 embedding 模型: {e}")
        print("跳过 Embedding 测试")
        return
    
    # 串行基准
    serial_results = await benchmark_embedding_serial(
        model,
        num_texts=100,  # 减少数量以加快测试
        batch_size=32,
        runs=2
    )
    serial_results.print_stats()
    
    # 并发优化
    concurrent_results = await benchmark_embedding_concurrent(
        model,
        num_texts=100,
        batch_size=32,
        max_concurrent=3,
        runs=2
    )
    concurrent_results.print_stats()
    
    # 对比
    compare_results(serial_results, concurrent_results)


async def run_image_upload_benchmark():
    """运行图片上传基准测试"""
    print("\n" + "="*60)
    print("🧪 图片上传并发性能测试")
    print("="*60)
    
    if not settings.MINIO_ENABLED:
        print("⚠️  MinIO 未启用，跳过图片上传测试")
        return
    
    # 串行基准
    serial_results = await benchmark_image_upload_serial(
        num_images=10,  # 减少数量以加快测试
        runs=2
    )
    serial_results.print_stats()
    
    # 并发优化
    concurrent_results = await benchmark_image_upload_concurrent(
        num_images=10,
        max_concurrent=5,
        runs=2
    )
    concurrent_results.print_stats()
    
    # 对比
    compare_results(serial_results, concurrent_results)


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="I/O 并发性能基准测试")
    parser.add_argument(
        "--test",
        choices=["all", "embedding", "image_upload"],
        default="all",
        help="选择要运行的测试"
    )
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("🚀 MimirQ I/O 并发性能基准测试")
    print("="*60)
    
    if args.test in ["all", "embedding"]:
        await run_embedding_benchmark()
    
    if args.test in ["all", "image_upload"]:
        await run_image_upload_benchmark()
    
    print("\n" + "="*60)
    print("✅ 基准测试完成")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
