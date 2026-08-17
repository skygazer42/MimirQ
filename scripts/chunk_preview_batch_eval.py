#!/usr/bin/env python3
"""
Batch chunk preview evaluator (offline).

Purpose:
- Quickly regression-test chunking configs across a folder of text/markdown files
  without spinning up the full backend stack.
- Produces per-file stats + quality gate + structured recommendation patches
  (same heuristics as /api/v1/documents/chunk-preview).

Limitations:
- Offset rebasing is best-effort: we locate chunk content in the original text using
  a forward cursor. For chunkers that rewrite content heavily, coverage signals may be noisy.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from langchain_core.documents import Document  # noqa: E402

from app.api.schemas.document import ChunkPreviewItem  # noqa: E402
from app.core.token_utils import estimate_tokens, num_tokens_from_string  # noqa: E402
from app.rag.chunking.factory import chunker_factory  # noqa: E402
from app.services.document_preview_utils import (  # noqa: E402
    _compute_chunk_coverage_metrics_from_ranges,
    _compute_chunk_preview_quality,
)


def _iter_files(paths: list[str]) -> Iterable[Path]:
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for ext in ("*.md", "*.txt"):
                yield from p.rglob(ext)
            continue
        if p.is_file():
            yield p


def _best_effort_offsets(full_text: str, chunk_texts: list[str]) -> list[tuple[int, int]]:
    """Find each chunk in the original text with a forward cursor (best-effort)."""
    out: list[tuple[int, int]] = []
    cursor = 0
    for t in chunk_texts:
        if not t:
            out.append((cursor, cursor))
            continue
        idx = full_text.find(t, cursor)
        if idx < 0:
            # Fallback: give it a monotonic offset to keep ordering stable.
            idx = cursor
        start = max(0, idx)
        end = start + len(t)
        out.append((start, end))
        cursor = max(cursor, end)
    return out


def _json_default(obj: Any) -> Any:
    try:
        return obj.model_dump()
    except Exception:
        return str(obj)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline batch chunk-preview evaluator")
    parser.add_argument("paths", nargs="+", help="Files or directories (recursively reads *.md/*.txt)")
    parser.add_argument(
        "--chunk-size", type=int, default=1000, help="chunk_size (chars or tokens depending on strategy)"
    )
    parser.add_argument("--chunk-overlap", type=int, default=200, help="chunk_overlap (ignored by separator strategy)")
    parser.add_argument("--strategy", type=str, default="langchain_recursive", help="chunk_strategy name")
    parser.add_argument("--max-files", type=int, default=0, help="Stop after N files (0 disables)")
    parser.add_argument("--max-chars", type=int, default=2_000_000, help="Skip files larger than this (chars)")
    parser.add_argument("--out", type=str, default="", help="Write JSONL to this path (default: stdout)")
    return parser


def _read_candidate(path: Path, *, max_chars: int) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    if not text.strip():
        return None
    if max_chars and len(text) > max_chars:
        return None
    return text


def _build_preview_items(text: str, chunks: list[Any], *, strategy: str) -> list[ChunkPreviewItem]:
    chunk_texts = [chunk.page_content or "" for chunk in chunks]
    offsets = _best_effort_offsets(text, chunk_texts)
    items: list[ChunkPreviewItem] = []
    for index, (chunk, (start, end)) in enumerate(zip(chunks, offsets, strict=False)):
        content = chunk.page_content or ""
        tokens_est = num_tokens_from_string(content) if strategy == "langchain_token" else estimate_tokens(content)
        items.append(
            ChunkPreviewItem(
                index=index,
                content=content,
                length=len(content),
                tokens_est=int(tokens_est or 0),
                start_index=int(start),
                end_index=int(end),
                page_number=(chunk.metadata or {}).get("page") if isinstance(chunk.metadata, dict) else None,
                metadata=dict(chunk.metadata or {}),
            )
        )
    return items


def _preview_stats(
    items: list[ChunkPreviewItem],
    coverage: dict[str, Any],
    *,
    strategy: str,
) -> SimpleNamespace:
    unit = "tokens" if strategy == "langchain_token" else "chars"
    threshold = 40 if unit == "tokens" else 120
    seen_hashes: set[str] = set()
    short_count = 0
    duplicate_count = 0
    for item in items:
        size = int(item.tokens_est or 0) if unit == "tokens" else int(item.length or 0)
        if 0 < size < threshold:
            short_count += 1
        trimmed = (item.content or "").strip()
        if not trimmed:
            continue
        digest = hashlib.sha256(trimmed.encode("utf-8", "ignore")).hexdigest()
        if digest in seen_hashes:
            duplicate_count += 1
        else:
            seen_hashes.add(digest)
    return SimpleNamespace(
        count=len(items),
        covered_chars=int(coverage.get("covered_chars", 0)),
        coverage_ratio=float(coverage.get("coverage_ratio", 0.0)),
        overlap_waste_ratio=float(coverage.get("overlap_waste_ratio", 0.0)),
        gap_count=int(coverage.get("gap_count", 0)),
        largest_gap=int(coverage.get("largest_gap", 0)),
        short_count=short_count,
        duplicate_count=duplicate_count,
    )


def _evaluate_file(
    path: Path,
    args: argparse.Namespace,
    *,
    strategy: str,
    effective_overlap: int,
) -> dict[str, Any] | None:
    text = _read_candidate(path, max_chars=int(args.max_chars or 0))
    if text is None:
        return None

    chunker = chunker_factory.get_chunker(strategy, int(args.chunk_size), effective_overlap)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"page": 1, "start_char": 0})]) or []
    items = _build_preview_items(text, list(chunks), strategy=strategy)
    total_chars = len(text)
    chunk_ranges = [(int(item.start_index or 0), int(item.end_index or 0)) for item in items]
    coverage = _compute_chunk_coverage_metrics_from_ranges(chunk_ranges, total_characters=total_chars)
    stats = _preview_stats(items, coverage, strategy=strategy)
    quality_gate, recommendations, patches = _compute_chunk_preview_quality(
        stats=stats,
        total_chunks=len(items),
        total_characters=total_chars,
        chunk_size=int(args.chunk_size),
        chunk_overlap=effective_overlap,
        original_text_included=True,
        original_text_truncated=False,
        original_text_max_chars=max(0, int(args.max_chars or 0)),
    )
    return {
        "file": str(path),
        "chars": total_chars,
        "strategy": strategy,
        "chunk_size": int(args.chunk_size),
        "chunk_overlap": effective_overlap,
        "chunks": len(items),
        "coverage": coverage,
        "quality_gate": _json_default(quality_gate),
        "recommendations": recommendations,
        "recommendation_patches": [patch.model_dump() for patch in (patches or [])],
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    strategy = chunker_factory.resolve_strategy(args.strategy)
    effective_overlap = 0 if strategy == "separator" else int(args.chunk_overlap)

    out_fp = None
    if args.out:
        out_fp = Path(args.out)
        out_fp.parent.mkdir(parents=True, exist_ok=True)
        fh = out_fp.open("w", encoding="utf-8")
    else:
        fh = sys.stdout

    processed = 0
    for path in _iter_files(list(args.paths)):
        if args.max_files and processed >= int(args.max_files):
            break
        row = _evaluate_file(path, args, strategy=strategy, effective_overlap=effective_overlap)
        if row is None:
            continue
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        processed += 1

    if fh is not sys.stdout:
        fh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
