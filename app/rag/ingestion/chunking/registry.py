from collections.abc import Iterator, Mapping
from importlib import import_module

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.capabilities import (
    CHUNKER_CAPABILITIES,
    ChunkerCapability,
)


class LazyChunkerRegistry(Mapping[str, type[BaseChunker]]):
    def __init__(self, capabilities: tuple[ChunkerCapability, ...]) -> None:
        self._capabilities = {item.strategy_name: item for item in capabilities}
        self._cache: dict[str, type[BaseChunker]] = {}

    def __getitem__(self, strategy_name: str) -> type[BaseChunker]:
        cached = self._cache.get(strategy_name)
        if cached is not None:
            return cached

        capability = self._capabilities[strategy_name]
        chunker_cls = getattr(import_module(capability.module_name), capability.class_name)
        self._cache[strategy_name] = chunker_cls
        return chunker_cls

    def __contains__(self, strategy_name: object) -> bool:
        return strategy_name in self._capabilities

    def __iter__(self) -> Iterator[str]:
        return iter(self._capabilities)

    def __len__(self) -> int:
        return len(self._capabilities)

    def get_capability(self, strategy_name: str) -> ChunkerCapability | None:
        return self._capabilities.get(strategy_name)


CHUNKER_STRATEGY_REGISTRY = LazyChunkerRegistry(CHUNKER_CAPABILITIES)

__all__ = ["CHUNKER_STRATEGY_REGISTRY", "LazyChunkerRegistry"]
