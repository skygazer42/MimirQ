from app.core.openai_compat import normalize_openai_compatible_base_url
from app.rag.embedding.adapter import create_langchain_embeddings_from_config


def test_normalize_openai_compatible_base_url_strips_known_suffixes() -> None:
    assert (
        normalize_openai_compatible_base_url("https://api.openai.com/v1/chat/completions")
        == "https://api.openai.com/v1"
    )
    assert (
        normalize_openai_compatible_base_url("http://localhost:8000/v1/embeddings")
        == "http://localhost:8000/v1"
    )
    assert (
        normalize_openai_compatible_base_url("https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings/")
        == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def test_create_langchain_embeddings_from_config_appends_embeddings_when_base_is_v1() -> None:
    emb = create_langchain_embeddings_from_config(
        provider="openai_compatible",
        model="text-embedding-3-small",
        api_key="no_api_key",
        base_url="http://localhost:8000/v1",
        dimension=3,
    )

    # Adapter wraps an internal BaseEmbeddingModel; we validate the normalized endpoint
    # to prevent accidental regressions that reintroduce "/v1" posts.
    model = getattr(emb, "_model", None)
    assert model is not None
    assert str(getattr(model, "base_url", "")).rstrip("/") == "http://localhost:8000/v1/embeddings"


def test_create_langchain_embeddings_from_config_supports_ollama() -> None:
    emb = create_langchain_embeddings_from_config(
        provider="ollama",
        model="bge-m3",
        api_key="no_api_key",
        base_url="",
        dimension=1024,
    )

    model = getattr(emb, "_model", None)
    assert model is not None
    assert model.__class__.__name__ == "OllamaEmbedding"
    assert str(getattr(model, "base_url", "")).rstrip("/").endswith("/api/embed")
