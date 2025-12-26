"""
RAGFlow legacy chunkers integration.

These chunkers were historically placed under `app.rag.chunking.legacy`. To keep the
backend pipeline coherent (parse -> governance -> chunk), this wrapper provides a
single canonical entry point under `app.rag.chunking`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Literal

ChunkStrategy = Literal["ragflow_naive", "ragflow_book", "ragflow_laws", "ragflow_email"]


def chunk_file(file_path: Path, *, strategy: ChunkStrategy, callback: Callable | None = None):
    strat = strategy.lower()
    if strat == "ragflow_naive":
        from app.rag.chunking.legacy.chunkers.naive import chunk as rf_chunk
    elif strat == "ragflow_book":
        from app.rag.chunking.legacy.chunkers.book import chunk as rf_chunk
    elif strat == "ragflow_laws":
        from app.rag.chunking.legacy.chunkers.laws import chunk as rf_chunk
    elif strat == "ragflow_email":
        from app.rag.chunking.legacy.chunkers.email import chunk as rf_chunk
    else:
        raise ValueError(f"Unsupported ragflow strategy: {strategy}")

    if callback is None:
        def callback(prog=None, msg=""):
            if msg:
                print(f"[ragflow] {msg} ({prog})")

    return rf_chunk(str(file_path), callback=callback)

