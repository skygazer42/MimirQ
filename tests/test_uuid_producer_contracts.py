import importlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Uuid, create_engine, literal, select


class NativeUUID(UUID):
    def __str__(self):
        raise RuntimeError("native UUID must not be serialized for another UUID conversion")


def test_document_access_validates_raw_group_ids_then_deduplicates_native_values():
    from app.api.schemas.documents.document import DocumentAccessUpdateRequest

    group_id = uuid4()
    request = DocumentAccessUpdateRequest(mode="partial_members", partial_group_list=[str(group_id), group_id])
    assert request.partial_group_list == [group_id]
    with pytest.raises(ValidationError):
        DocumentAccessUpdateRequest(mode="partial_members", partial_group_list=["invalid-group-id"])


def test_catalog_store_returns_uuid_produced_by_flushed_orm_rows():
    from app.connectors.catalog import CatalogTableInput
    from app.connectors.store import SQLAlchemyCatalogStore as SqlAlchemyCatalogStore

    class CatalogSession:
        current = None

        def query(self, _model):
            return self

        def filter(self, *_clauses):
            return self

        def first(self):
            return self.current

        def add(self, row):
            self.current = row

        def flush(self):
            if self.current.id is None:
                self.current.id = NativeUUID(int=uuid4().int)

    db = CatalogSession()
    store = SqlAlchemyCatalogStore(db=db)
    table = CatalogTableInput(
        engine="mysql",
        db_name="source",
        schema_name=None,
        table_name="records",
        table_type="table",
        comment=None,
        fingerprint="fingerprint",
    )
    first = store.upsert_table(
        tenant_id=uuid4(), dataset_id=uuid4(), connector_config_id=None, table=table, seen_at=datetime.now(UTC)
    )
    assert first is db.current.id
    second = store.upsert_table(
        tenant_id=uuid4(), dataset_id=uuid4(), connector_config_id=None, table=table, seen_at=datetime.now(UTC)
    )
    assert second is first
    snapshot = store.insert_profile_snapshot(table_id=first, entitlement_hash="hash", profile={}, sample_meta={})
    assert snapshot is db.current.id


def test_category_tree_uses_native_parent_ids_and_keeps_sorting_and_depth():
    from app.models.datasets.records import DatasetCategory
    from app.services.datasets.categories import build_category_tree_nodes

    parent_id, first_id, second_id = uuid4(), uuid4(), uuid4()
    rows = [
        DatasetCategory(id=second_id, parent_id=parent_id, name="Second", sort_order=2),
        DatasetCategory(id=parent_id, parent_id=None, name="Parent", sort_order=0),
        DatasetCategory(id=first_id, parent_id=parent_id, name="First", sort_order=1),
    ]
    tree = build_category_tree_nodes(rows)
    assert [node.id for node in tree] == [parent_id]
    assert [node.id for node in tree[0].children] == [first_id, second_id]
    assert [node.depth for node in tree[0].children] == [1, 1]


@pytest.mark.parametrize(
    ("module_name", "argument"),
    [("scripts.seed_public_bench_cfever_dev", "cases"), ("scripts.seed_public_bench_miracl_zh_pool", "case_items")],
)
def test_benchmark_reference_integrity_consumes_actual_uuid_rows(monkeypatch, module_name, argument):
    module = importlib.import_module(module_name)
    present, absent = uuid4(), uuid4()
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        rows = connection.execute(select(literal(present, type_=Uuid).label("id"))).all()
    engine.dispose()

    class ReferenceSession:
        def query(self, *_columns):
            return self

        def join(self, *_clauses):
            return self

        def filter(self, *_clauses):
            return self

        def all(self):
            return rows

        def close(self):
            pass

    monkeypatch.setattr(module, "SessionLocal", ReferenceSession)
    monkeypatch.setattr(module, "_iter_reference_chunk_ids", lambda **_kwargs: [present, absent])
    result = module.verify_reference_integrity(tenant_id=uuid4(), dataset_id=uuid4(), **{argument: []})
    assert result["checked"] == 2
    assert result["missing"] == 1
    assert result["missing_sample"] == [str(absent)]
