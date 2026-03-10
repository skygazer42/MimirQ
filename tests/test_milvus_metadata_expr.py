from app.storage.vector.milvus import _build_milvus_metadata_expr


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
