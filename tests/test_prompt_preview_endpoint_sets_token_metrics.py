from pathlib import Path


def test_prompt_preview_endpoint_uses_prompt_preview_metrics_helper():
    src = Path("app/api/v1/rag.py").read_text(encoding="utf-8")

    # The prompt-preview endpoint should surface token breakdown fields (O34),
    # implemented via a dedicated helper for unit-testability.
    assert "compute_prompt_preview_metrics" in src

    helper_src = Path("app/rag/core/prompt_preview_metrics.py").read_text(encoding="utf-8")
    assert "prompt_tokens" in helper_src
    assert "context_tokens" in helper_src
    assert "history_tokens" in helper_src
