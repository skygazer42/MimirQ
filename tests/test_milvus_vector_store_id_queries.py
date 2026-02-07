from __future__ import annotations


class _FakeCollection:
    def __init__(self, *, existing_ids: set[str], max_expr_chars: int | None = None) -> None:
        self._existing = set(existing_ids or set())
        self._max_expr_chars = int(max_expr_chars) if max_expr_chars is not None else None

    def query(self, *, expr: str, output_fields: list[str], **_kwargs):  # noqa: ANN001
        if self._max_expr_chars is not None:
            assert len(expr) <= self._max_expr_chars
        assert output_fields == ["id"]

        expr0 = str(expr or "")
        if " in [" in expr0:
            # expr: id in ["a", "b"]
            raw = expr0.split("[", 1)[-1].rsplit("]", 1)[0]
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            want = [p.strip().strip('"').replace('\\"', '"').replace("\\\\", "\\") for p in parts]
            return [{"id": x} for x in want if x in self._existing]

        # dataset listing path: return the whole set (bounded by caller via limit/offset).
        return [{"id": x} for x in sorted(self._existing)]


class _FakeStore:
    def __init__(self, col: _FakeCollection) -> None:
        self._primary_field = "id"
        self.col = col


def test_fetch_existing_ids_returns_subset() -> None:
    from app.storage.vector.milvus import MilvusVectorStore

    store = MilvusVectorStore()
    store._store = _FakeStore(_FakeCollection(existing_ids={"a", "c"}))  # type: ignore[attr-defined]

    assert store.fetch_existing_ids(["a", "b", "c", "a"]) == {"a", "c"}


def test_fetch_existing_ids_chunks_expr_to_avoid_server_rejects() -> None:
    from app.storage.vector.milvus import _MILVUS_EXPR_MAX_CHARS, MilvusVectorStore

    ids = [("x" * 120) + str(i) for i in range(240)]
    store = MilvusVectorStore()
    store._store = _FakeStore(  # type: ignore[attr-defined]
        _FakeCollection(existing_ids=set(ids), max_expr_chars=int(_MILVUS_EXPR_MAX_CHARS))
    )

    assert store.fetch_existing_ids(ids) == set(ids)


def test_list_ids_by_dataset_returns_ids() -> None:
    from uuid import UUID

    from app.storage.vector.milvus import MilvusVectorStore

    store = MilvusVectorStore()
    store._store = _FakeStore(_FakeCollection(existing_ids={"id1", "id2"}))  # type: ignore[attr-defined]

    out = store.list_ids_by_dataset(
        tenant_id=UUID("00000000-0000-0000-0000-000000000000"),
        dataset_id=UUID("11111111-1111-1111-1111-111111111111"),
        limit=10,
        offset=0,
    )
    assert set(out) == {"id1", "id2"}
