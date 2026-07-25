from app import main
from app.rag.preprocessing import tokenization


def test_tokenizer_warmup_initializes_jieba_and_exercises_mixed_text(monkeypatch) -> None:
    initialized: list[bool] = []
    tokenized: list[str] = []

    monkeypatch.setattr(tokenization.jieba, "initialize", lambda: initialized.append(True))
    monkeypatch.setattr(
        tokenization,
        "tokenize_for_bm25",
        lambda text: tokenized.append(text) or ["mimirq", "knowledge", "知识", "检索"],
    )

    tokenization.warmup_bm25_tokenizer()

    assert initialized == [True]
    assert tokenized and not tokenized[0].isascii()


def test_startup_warms_tokenizer_when_bm25_is_enabled(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(main.settings, "BM25_INDEX_ENABLED", True)
    monkeypatch.setattr(tokenization, "warmup_bm25_tokenizer", lambda: calls.append(True))

    main._warmup_retrieval_tokenizer()

    assert calls == [True]


def test_startup_skips_tokenizer_warmup_when_bm25_is_disabled(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(main.settings, "BM25_INDEX_ENABLED", False)
    monkeypatch.setattr(tokenization, "warmup_bm25_tokenizer", lambda: calls.append(True))

    main._warmup_retrieval_tokenizer()

    assert calls == []
