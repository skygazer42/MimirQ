import pytest

from app.rag.retrieval.hybrid.common import _apply_exact_content_bonus_to_result
from app.rag.retrieval.hybrid.result_values import result_key
from app.rag.retrieval.hybrid.text_preparation import rerank_text_from_result


@pytest.mark.parametrize("consumer", [result_key, rerank_text_from_result])
def test_retrieval_result_consumers_require_the_text_field(consumer):
    with pytest.raises(KeyError, match="content"):
        consumer({"metadata": {}})


@pytest.mark.parametrize("content", [None, 0, False])
def test_reranking_rejects_invalid_required_result_text(content):
    with pytest.raises((AttributeError, TypeError)):
        rerank_text_from_result({"content": content, "metadata": {}})


def test_exact_phrase_bonus_exposes_a_missing_result_text_field():
    with pytest.raises(KeyError, match="content"):
        _apply_exact_content_bonus_to_result(query="tenant isolation", result={"metadata": {}}, phrase_boost_weight=1.0)
