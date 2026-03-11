from __future__ import annotations

from pathlib import Path


def test_retrieval_api_examples_docs_cover_retrieve_explain_and_eval_cli() -> None:
    md = Path("docs/examples/retrieval_api_examples.md").read_text(encoding="utf-8")
    http = Path("docs/examples/retrieval_api_examples.http").read_text(encoding="utf-8")

    assert "/api/v1/retrieval/profiles" in md
    assert "/api/v1/retrieval/explain" in md
    assert "scripts/regression_gate.py" in md
    assert "scripts/retrieval_ablation.py" in md

    assert "GET {{base_url}}/api/v1/retrieval/profiles" in http
    assert "POST {{base_url}}/api/v1/retrieval/explain" in http
    assert "POST {{base_url}}/api/v1/retrieval/config-hash" in http


def test_docs_index_links_retrieval_api_examples() -> None:
    text = Path("docs/README.md").read_text(encoding="utf-8")
    assert "examples/retrieval_api_examples.md" in text

