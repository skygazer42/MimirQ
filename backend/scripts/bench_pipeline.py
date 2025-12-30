"""
本地基准脚本：文档解析 ->（可选）治理清洗 -> 切块

用途：
- 给优化前后提供一个稳定的时间/内存基线
- 默认不做“写库/向量化/MinIO 上传”，避免本地环境差异导致不可比

示例：
  python scripts/bench_pipeline.py backend/app/deepdoc/data/picture.pdf --chunk-strategy langchain_recursive
  python scripts/bench_pipeline.py xxx.pdf --parser-backend auto --governance
"""

from __future__ import annotations

import argparse
import time
import tracemalloc
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.parsing.factory import parser_factory
from app.rag.chunking.factory import chunker_factory
from app.rag.preprocessing.processor import governance_processor


def _fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:.2f}ms"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=str, help="待处理文件路径（pdf/md/txt 等）")
    ap.add_argument("--parser-backend", type=str, default="auto", help="auto/basic/mineru/deepdoc/markitdown 等")
    ap.add_argument("--chunk-strategy", type=str, default="langchain_recursive", help="切块策略（见 chunker_factory）")
    ap.add_argument("--chunk-size", type=int, default=None, help="覆盖默认 chunk_size")
    ap.add_argument("--chunk-overlap", type=int, default=None, help="覆盖默认 chunk_overlap")
    ap.add_argument("--governance", action="store_true", help="启用治理清洗（默认关闭以减少环境差异）")
    args = ap.parse_args()

    file_path = Path(args.file).expanduser().resolve()
    if not file_path.exists():
        raise SystemExit(f"File not found: {file_path}")

    chunk_size = int(args.chunk_size or getattr(settings, "CHUNK_SIZE", 1000))
    chunk_overlap = int(args.chunk_overlap or getattr(settings, "CHUNK_OVERLAP", 200))
    resolved_chunk_strategy = chunker_factory.resolve_strategy(args.chunk_strategy)

    dataset_id = "bench"
    document_id = str(uuid4())

    tracemalloc.start()
    t0 = time.perf_counter()

    t_parse0 = time.perf_counter()
    documents, resolved_backend = parser_factory.parse(
        file_path,
        parser_backend=args.parser_backend,
        dataset_id=dataset_id,
        document_id=document_id,
    )
    t_parse = time.perf_counter() - t_parse0

    t_gov = 0.0
    if args.governance:
        t_gov0 = time.perf_counter()
        documents, stats = governance_processor.clean_documents(documents)
        t_gov = time.perf_counter() - t_gov0
    else:
        stats = None

    t_chunk0 = time.perf_counter()
    chunker = chunker_factory.get_chunker(
        resolved_chunk_strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    chunks = chunker.split_documents(documents)
    t_chunk = time.perf_counter() - t_chunk0

    total = time.perf_counter() - t0
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total_chars = sum(len((c.page_content or "")) for c in chunks)

    print("=== bench_pipeline ===")
    print(f"file: {file_path}")
    print(f"parser_backend(requested): {args.parser_backend}")
    print(f"parser_backend(resolved):  {resolved_backend}")
    print(f"chunk_strategy: {resolved_chunk_strategy}")
    print(f"chunk_size/overlap: {chunk_size}/{chunk_overlap}")
    print(f"docs: {len(documents)} chunks: {len(chunks)} total_chars: {total_chars}")
    if stats is not None:
        print(f"governance: docs={stats.documents} changed={stats.changed} rules={stats.applied_rules}")
    print(f"time.parse: {_fmt_ms(t_parse)} time.gov: {_fmt_ms(t_gov)} time.chunk: {_fmt_ms(t_chunk)} time.total: {_fmt_ms(total)}")
    print(f"mem.peak: {peak / 1024 / 1024:.2f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


