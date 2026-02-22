from app.rag.kg.extraction.evidence import find_evidence_span, surface_mentioned


def test_find_evidence_span_exact_substring() -> None:
    text = "Alice works with Bob."
    assert find_evidence_span(text, "works with") == (6, 16)


def test_find_evidence_span_whitespace_flex() -> None:
    text = "Alice works\nwith Bob."
    # The quote differs by whitespace; matcher should still find it.
    span = find_evidence_span(text, "works with")
    assert span == (6, 16)


def test_find_evidence_span_ascii_ignorecase_fallback() -> None:
    text = "We use OpenAI embeddings."
    # Evidence quotes from models sometimes differ in casing; allow ignorecase fallback for longer ASCII quotes.
    span = find_evidence_span(text, "openai")
    assert span == (7, 13)


def test_find_evidence_span_does_not_ignorecase_match_too_short_tokens() -> None:
    text = "We use us as a pronoun here."
    # Guardrail: don't try ignorecase matching for very short tokens.
    assert find_evidence_span(text, "US") is None


def test_surface_mentioned_normalizes_edges_and_whitespace() -> None:
    quote = "（OpenAI） works with  Bob."
    assert surface_mentioned(quote=quote, surface="OpenAI") is True
    assert surface_mentioned(quote=quote, surface="Bob") is True
    assert surface_mentioned(quote=quote, surface="Charlie") is False

