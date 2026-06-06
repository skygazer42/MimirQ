from __future__ import annotations


def test_index_content_uses_plugin_retrieval_text_without_losing_display_content():
    from app.services.indexer import _chunk_index_content

    meta = {
        "_retrieval_text": "业务类型：demo\n内容：for recall",
    }

    index_text, next_meta = _chunk_index_content("clean display body", meta)

    assert index_text == "业务类型：demo\n内容：for recall"
    assert next_meta["_retrieval_display_content"] == "clean display body"


def test_index_content_falls_back_to_chunk_content_when_retrieval_text_is_missing():
    from app.services.indexer import _chunk_index_content

    index_text, next_meta = _chunk_index_content("clean display body", {})

    assert index_text == "clean display body"
    assert "_retrieval_display_content" not in next_meta
