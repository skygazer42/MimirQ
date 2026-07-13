#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.core.token_utils import estimate_tokens
from app.rag.chunking.factory import chunker_factory
from app.rag.chunking.quality_scorer import detect_context_cliff
from app.services.chunking_stats_utils import (
    compute_chunking_stats_from_texts,
    compute_chunking_stats_from_texts_tokens,
)

_DEFAULT_CHUNK_SIZES = (256, 512, 1024)
_DEFAULT_OVERLAP_RATIOS = (0.0, 0.10, 0.25)
_DEFAULT_STRATEGIES = (
    "langchain_recursive",
    "semantic_sentence",
    "sentence_window",
    "parent_child",
)
_ILYA_CONTROL_GROUP = {
    "strategy": "langchain_recursive",
    "chunk_size": 300,
    "chunk_overlap_ratio": round(50.0 / 300.0, 4),
    "chunk_overlap": 50,
    "control_group": "ilya_300_50",
}


def build_chunking_grid_configs(
    *,
    chunk_sizes: tuple[int, ...] = _DEFAULT_CHUNK_SIZES,
    overlap_ratios: tuple[float, ...] = _DEFAULT_OVERLAP_RATIOS,
    strategies: tuple[str, ...] = _DEFAULT_STRATEGIES,
) -> list[dict[str, Any]]:
    grid: list[dict[str, Any]] = [dict(_ILYA_CONTROL_GROUP)]
    for strategy in strategies:
        for chunk_size in chunk_sizes:
            for ratio in overlap_ratios:
                overlap = int(round(int(chunk_size) * float(ratio)))
                grid.append(
                    {
                        "strategy": str(strategy),
                        "chunk_size": int(chunk_size),
                        "chunk_overlap_ratio": float(ratio),
                        "chunk_overlap": int(overlap),
                    }
                )
    return grid


def evaluate_chunking_grid_file(
    *,
    path: Path,
    strategy: str,
    chunk_size: int,
    chunk_overlap: int,
) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    resolved_strategy = chunker_factory.resolve_strategy(strategy)
    chunker = chunker_factory.get_chunker(resolved_strategy, int(chunk_size), int(chunk_overlap))
    chunks = chunker.split_documents([Document(page_content=text, metadata={"source": str(path)})])
    chunk_texts = [str(c.page_content or "") for c in (chunks or [])]
    token_counts = [int(estimate_tokens(chunk_text) or 0) for chunk_text in chunk_texts]
    char_stats = compute_chunking_stats_from_texts(chunk_texts) or {}
    token_stats = compute_chunking_stats_from_texts_tokens(chunk_texts) or {}
    cliff_count = sum(1 for count in token_counts if detect_context_cliff(count).get("cliff_risk") != "none")
    return {
        "file": str(path),
        "strategy": str(strategy),
        "resolved_strategy": str(resolved_strategy),
        "chunk_size": int(chunk_size),
        "chunk_overlap": int(chunk_overlap),
        "chunk_count": int(len(chunks or [])),
        "total_tokens_est": int(token_stats.get("total") or 0),
        "median_tokens_est": int(token_stats.get("median") or 0),
        "avg_chunk_chars": int(char_stats.get("avg") or 0),
        "cliff_rate": round(cliff_count / len(token_counts), 4) if token_counts else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline chunking grid runner")
    parser.add_argument("paths", nargs="+", help="Files to evaluate")
    parser.add_argument("--out", type=str, default="", help="Optional JSONL output path")
    args = parser.parse_args(argv)

    rows: list[dict[str, Any]] = []
    grid = build_chunking_grid_configs()
    for raw in args.paths:
        path = Path(raw)
        if not path.exists() or not path.is_file():
            continue
        for cfg in grid:
            rows.append(
                evaluate_chunking_grid_file(
                    path=path,
                    strategy=str(cfg["strategy"]),
                    chunk_size=int(cfg["chunk_size"]),
                    chunk_overlap=int(cfg["chunk_overlap"]),
                )
            )

    payload = rows
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in payload) + ("\n" if payload else ""), encoding="utf-8")
    else:
        for row in payload:
            print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
