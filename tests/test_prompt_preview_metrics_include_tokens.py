from app.rag.core.prompt_preview_metrics import compute_prompt_preview_metrics


def test_compute_prompt_preview_metrics_includes_token_breakdown():
    metrics = compute_prompt_preview_metrics(
        prompt_text="Hello world!",
        context="Context block.",
        history="User: hi\nAssistant: hello",
        elapsed_sec=1.23456,
        context_build_elapsed_sec=0.11111,
        prompt_render_elapsed_sec=0.22222,
    )

    assert metrics["prompt_chars"] == len("Hello world!")
    assert metrics["context_chars"] == len("Context block.")
    assert metrics["history_chars"] == len("User: hi\nAssistant: hello")

    assert isinstance(metrics["prompt_tokens"], int)
    assert isinstance(metrics["context_tokens"], int)
    assert isinstance(metrics["history_tokens"], int)

    assert metrics["prompt_tokens"] > 0
    assert metrics["context_tokens"] > 0
    assert metrics["history_tokens"] > 0

    assert metrics["elapsed_sec"] == 1.235
    assert metrics["context_build_elapsed_sec"] == 0.111
    assert metrics["prompt_render_elapsed_sec"] == 0.222

