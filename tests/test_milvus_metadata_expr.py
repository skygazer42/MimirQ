from app.storage.vector.milvus import (
    _INDEXED_METADATA_FILTERS_KEY,
    _build_milvus_metadata_expr,
    _flatten_indexed_metadata_slots,
    _rehydrate_indexed_metadata_slots,
    _sanitize_milvus_metadata_filter,
)


def test_build_milvus_metadata_expr_none():
    assert _build_milvus_metadata_expr(None) is None
    assert _build_milvus_metadata_expr("nope") is None
    assert _build_milvus_metadata_expr({}) is None


def test_build_milvus_metadata_expr_ignores_unknown_fields():
    assert _build_milvus_metadata_expr({"__proto__": {"$eq": "x"}}) is None


def test_build_milvus_metadata_expr_string_eq():
    expr = _build_milvus_metadata_expr({"tenant_id": {"$eq": "t1"}})
    assert expr == 'tenant_id == "t1"'

def test_build_milvus_metadata_expr_dataset_id_eq():
    expr = _build_milvus_metadata_expr({"dataset_id": {"$eq": "d1"}})
    assert expr == 'dataset_id == "d1"'


def test_build_milvus_metadata_expr_embedding_space_hash_eq():
    expr = _build_milvus_metadata_expr({"embedding_space_hash": {"$eq": "h1"}})
    assert expr == 'embedding_space_hash == "h1"'


def test_build_milvus_metadata_expr_numeric_gte():
    expr = _build_milvus_metadata_expr({"page_number": {"$gte": 3}})
    assert expr == "page_number >= 3"


def test_build_milvus_metadata_expr_in_list():
    expr = _build_milvus_metadata_expr({"document_id": {"$in": ["a", "b"]}})
    assert expr == 'document_id in ["a", "b"]'


def test_build_milvus_metadata_expr_rejects_bad_field_names():
    assert _build_milvus_metadata_expr({"tenant_id;drop": {"$eq": "x"}}) is None


def test_build_milvus_metadata_expr_unsupported_ops_are_skipped():
    assert _build_milvus_metadata_expr({"tenant_id": {"$contains": "x"}}) is None


def test_milvus_metadata_expr_pushes_down_indexed_metadata_business_field():
    supported = _sanitize_milvus_metadata_filter(
        {
            "dataset_id": "dataset-a",
            "business_type": {"$eq": "demo_service"},
        }
    )

    assert supported["dataset_id"] == "dataset-a"
    assert supported[_INDEXED_METADATA_FILTERS_KEY] == [
        {"field": "business_type", "condition": {"$eq": "demo_service"}}
    ]
    expr = _build_milvus_metadata_expr(supported)

    assert expr is not None
    assert 'dataset_id == "dataset-a"' in expr
    assert 'indexed_meta_01_key == "business_type"' in expr
    assert 'indexed_meta_01_value == "demo_service"' in expr


def test_milvus_metadata_expr_accepts_explicit_indexed_metadata_path():
    supported = _sanitize_milvus_metadata_filter(
        {
            "_indexed_metadata.district": {"$in": ["north-region", "south-region"]},
        }
    )
    expr = _build_milvus_metadata_expr(supported)

    assert supported[_INDEXED_METADATA_FILTERS_KEY] == [
        {"field": "district", "condition": {"$in": ["north-region", "south-region"]}}
    ]
    assert expr is not None
    assert 'indexed_meta_01_key == "district"' in expr
    assert 'indexed_meta_01_value in ["north-region", "south-region"]' in expr


def test_milvus_indexed_metadata_slots_round_trip():
    slots = _flatten_indexed_metadata_slots(
        {
            "_indexed_metadata": {
                "business_type": "demo_service",
                "tags": ["就业", "创业"],
                "empty": "",
            }
        }
    )

    assert slots["indexed_meta_01_key"] == "business_type"
    assert slots["indexed_meta_01_value"] == "demo_service"
    assert slots["indexed_meta_02_key"] == "tags"
    assert slots["indexed_meta_02_value"] == "就业"
    assert slots["indexed_meta_03_key"] == "tags"
    assert slots["indexed_meta_03_value"] == "创业"

    rehydrated = _rehydrate_indexed_metadata_slots(dict(slots))
    assert rehydrated["_indexed_metadata"] == {
        "business_type": "demo_service",
        "tags": ["就业", "创业"],
    }
