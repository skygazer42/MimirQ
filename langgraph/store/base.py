from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from threading import RLock
from typing import Any, Generic, TypeVar

ValueT = TypeVar("ValueT")

StoreNamespace = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoreItem(Generic[ValueT]):
    """A single store record."""

    namespace: StoreNamespace
    key: str
    value: ValueT
    updated_at: float | None = None


class BaseStore(abc.ABC):
    """A minimal key-value store interface expected by LangGraph 1.0.x."""

    @abc.abstractmethod
    def get(self, namespace: StoreNamespace, key: str) -> StoreItem[Any] | None:
        raise NotImplementedError

    @abc.abstractmethod
    def put(self, namespace: StoreNamespace, key: str, value: Any) -> StoreItem[Any]:
        raise NotImplementedError

    def delete(self, namespace: StoreNamespace, key: str) -> None:
        return None

    async def aget(self, namespace: StoreNamespace, key: str) -> StoreItem[Any] | None:
        return self.get(namespace, key)

    async def aput(self, namespace: StoreNamespace, key: str, value: Any) -> StoreItem[Any]:
        return self.put(namespace, key, value)

    async def adelete(self, namespace: StoreNamespace, key: str) -> None:
        self.delete(namespace, key)


class InMemoryStore(BaseStore):
    """Thread-safe in-memory store (non-persistent)."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._data: dict[tuple[StoreNamespace, str], StoreItem[Any]] = {}

    def get(self, namespace: StoreNamespace, key: str) -> StoreItem[Any] | None:
        with self._lock:
            return self._data.get((namespace, key))

    def put(self, namespace: StoreNamespace, key: str, value: Any) -> StoreItem[Any]:
        item = StoreItem(namespace=namespace, key=key, value=value, updated_at=time.time())
        with self._lock:
            self._data[(namespace, key)] = item
        return item

    def delete(self, namespace: StoreNamespace, key: str) -> None:
        with self._lock:
            self._data.pop((namespace, key), None)
