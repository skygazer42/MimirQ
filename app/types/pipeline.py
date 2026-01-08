"""
Internal configuration types for document pipeline (not API Schema)

Notes:
- PipelineOptions/PipelineEffective are internal structures used by service layer when parsing doc_metadata and settings
- Should not be placed in app/api/schemas (avoid polluting API schema layer with internal config)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PipelineOptions:
    governance_enabled: Optional[bool] = None
    governance_remove_toc_lines: Optional[bool] = None
    governance_remove_noise_lines: Optional[bool] = None
    governance_unwrap_lines: Optional[bool] = None
    governance_remove_common_lines: Optional[bool] = None
    governance_unwrap_max_line_length: Optional[int] = None
    governance_noise_min_chars: Optional[int] = None
    governance_noise_ratio_threshold: Optional[float] = None
    governance_common_lines_min_docs: Optional[int] = None
    governance_common_lines_min_ratio: Optional[float] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    chunk_vector_enabled: Optional[bool] = None
    bm25_index_enabled: Optional[bool] = None
    kg_enabled: Optional[bool] = None
    event_vector_enabled: Optional[bool] = None
    entity_vector_enabled: Optional[bool] = None


@dataclass(frozen=True)
class PipelineEffective:
    governance_enabled: bool
    governance_remove_toc_lines: bool
    governance_remove_noise_lines: bool
    governance_unwrap_lines: bool
    governance_remove_common_lines: bool
    governance_unwrap_max_line_length: int
    governance_noise_min_chars: int
    governance_noise_ratio_threshold: float
    governance_common_lines_min_docs: int
    governance_common_lines_min_ratio: float
    chunk_size: int
    chunk_overlap: int
    chunk_vector_enabled: bool
    bm25_index_enabled: bool
    kg_enabled: bool
    event_vector_enabled: bool
    entity_vector_enabled: bool


__all__ = [
    "PipelineEffective",
    "PipelineOptions",
]


