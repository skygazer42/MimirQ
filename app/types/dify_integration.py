"""Internal Dify actor identity and knowledge graph execution flags."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class DifyActor:
    tenant_id: UUID
    account_id: str


@dataclass(frozen=True)
class DifyKGFlags:
    enable_query_expansion: bool
    enable_chunk_injection: bool
    chunk_injection_max_chunks: int
    enable_chunk_boost: bool
    chunk_boost_weight: float
    chunk_boost_max_promoted: int

    @property
    def enabled(self) -> bool:
        return self.enable_query_expansion or self.enable_chunk_injection or self.enable_chunk_boost


__all__ = [
    "DifyActor",
    "DifyKGFlags",
]
