from app.storage.vector.milvus import get_milvus_adapter


def test_get_milvus_adapter_caches_instances():
    a1 = get_milvus_adapter("test_collection", vector_field="embedding", text_field="content")
    a2 = get_milvus_adapter("test_collection", vector_field="embedding", text_field="content")
    b1 = get_milvus_adapter("test_collection", vector_field="vec", text_field="content")

    assert a1 is a2
    assert a1 is not b1

