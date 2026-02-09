from __future__ import annotations


def test_classify_chunk_semantic_role_detects_code_fences() -> None:
    from app.rag.chunking.roles import ChunkSemanticRole, classify_chunk_semantic_role

    role = classify_chunk_semantic_role(content="```python\nprint('hi')\n```", meta={})
    assert role == ChunkSemanticRole.CODE.value


def test_classify_chunk_semantic_role_detects_markdown_tables() -> None:
    from app.rag.chunking.roles import ChunkSemanticRole, classify_chunk_semantic_role

    md = "\n".join(
        [
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
        ]
    )
    role = classify_chunk_semantic_role(content=md, meta={})
    assert role == ChunkSemanticRole.TABLE.value


def test_classify_chunk_semantic_role_detects_procedure_by_steps() -> None:
    from app.rag.chunking.roles import ChunkSemanticRole, classify_chunk_semantic_role

    text = "1. Do this\n2. Do that\n3. Done\n"
    role = classify_chunk_semantic_role(content=text, meta={})
    assert role == ChunkSemanticRole.PROCEDURE.value


def test_classify_chunk_semantic_role_uses_header_keywords() -> None:
    from app.rag.chunking.roles import ChunkSemanticRole, classify_chunk_semantic_role

    role = classify_chunk_semantic_role(content="Anything", meta={"header_path": "FAQ"})
    assert role == ChunkSemanticRole.FAQ.value


def test_classify_chunk_semantic_role_uses_chunk_strategy_hints() -> None:
    from app.rag.chunking.roles import ChunkSemanticRole, classify_chunk_semantic_role

    role = classify_chunk_semantic_role(content="Term: definition", meta={"chunk_strategy": "glossary"})
    assert role == ChunkSemanticRole.DEFINITION.value

