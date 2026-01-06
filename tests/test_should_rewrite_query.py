from app.rag.core.text import should_rewrite_query


def test_should_rewrite_query_empty_false():
    assert should_rewrite_query("") is False


def test_should_rewrite_query_short_true():
    assert should_rewrite_query("怎么做？", short_len=12) is True


def test_should_rewrite_query_trigger_true():
    assert should_rewrite_query("它的优缺点是什么？", short_len=4) is True


def test_should_rewrite_query_long_no_trigger_false():
    assert should_rewrite_query("Explain how the retrieval pipeline works end-to-end.", short_len=4) is False

