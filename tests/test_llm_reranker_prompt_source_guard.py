from pathlib import Path


def test_llm_reranker_prompt_escapes_json_example_braces() -> None:
    text = Path("app/rag/reranker/llm_based.py").read_text(encoding="utf-8")

    assert '[{{"id": "...", "score": 0.0}}]' in text
    assert '[{"id": "...", "score": 0.0}]' not in text
