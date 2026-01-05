from __future__ import annotations

import abc
import time
from collections.abc import Iterable, Mapping
from threading import RLock
from typing import Generic, TypeVar

ValueT = TypeVar("ValueT")

CacheNamespace = tuple[str, ...]
CacheKey = tuple[CacheNamespace, str]


class BaseCache(Generic[ValueT], abc.ABC):
    """A minimal cache interface expected by LangGraph 1.0.x.

    Upstream LangGraph currently imports `langgraph.cache.base.BaseCache`, but some
    releases ship without that module. This local implementation provides the API
    used by LangGraph's runtime (`get/set/clear` + async variants).
    """

    @abc.abstractmethod
    def get(self, keys: Iterable[CacheKey]) -> dict[CacheKey, ValueT]:
        raise NotImplementedError

    @abc.abstractmethod
    def set(self, values: Mapping[CacheKey, tuple[ValueT, int | None]]) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def clear(self, namespaces: Iterable[CacheNamespace]) -> None:
        raise NotImplementedError

    async def aget(self, keys: Iterable[CacheKey]) -> dict[CacheKey, ValueT]:
        return self.get(keys)

    async def aset(self, values: Mapping[CacheKey, tuple[ValueT, int | None]]) -> None:
        self.set(values)

    async def aclear(self, namespaces: Iterable[CacheNamespace]) -> None:
        self.clear(namespaces)


class InMemoryCache(BaseCache[ValueT]):
    """Thread-safe in-memory cache with optional TTL support."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._data: dict[CacheKey, tuple[ValueT, float | None]] = {}

    def get(self, keys: Iterable[CacheKey]) -> dict[CacheKey, ValueT]:
        now = time.time()
        found: dict[CacheKey, ValueT] = {}
        with self._lock:
            for key in keys:
                value_and_expiry = self._data.get(key)
                if value_and_expiry is None:
                    continue
                value, expiry = value_and_expiry
                if expiry is not None and expiry <= now:
                    self._data.pop(key, None)
                    continue
                found[key] = value
        return found

    def set(self, values: Mapping[CacheKey, tuple[ValueT, int | None]]) -> None:
        now = time.time()
        with self._lock:
            for key, (value, ttl) in values.items():
                expiry = (now + ttl) if ttl is not None else None
                self._data[key] = (value, expiry)

    def clear(self, namespaces: Iterable[CacheNamespace]) -> None:
        prefixes = tuple(namespaces)
        if not prefixes:
            return

        with self._lock:
            keys_to_delete: list[CacheKey] = []
            for (ns, key) in self._data.keys():
                for prefix in prefixes:
                    if ns[: len(prefix)] == prefix:
                        keys_to_delete.append((ns, key))
                        break
            for k in keys_to_delete:
                self._data.pop(k, None)
