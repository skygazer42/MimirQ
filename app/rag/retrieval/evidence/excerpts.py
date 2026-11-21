"""Select query-relevant evidence excerpts and map spans to their source text."""

import re

_SENTENCE_RE = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?", flags=re.S)
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}")
_SENTENCE_BOUNDARIES = {"。", "！", "？", ".", "!", "?", "\n"}


def _truncate_with_ellipsis(text: str, *, max_chars: int) -> str:
    return (text[:max_chars] + "...") if max_chars and len(text) > max_chars else text


def raw_index_from_casefold_index(text: str, folded_index: int) -> int:
    """Map a matched casefold offset to the original text without retaining an index map."""
    folded_end = 0
    for raw_index, character in enumerate(text):
        folded_end += len(character.casefold())
        if folded_index < folded_end:
            return raw_index
    raise IndexError("Casefold match index is outside the source text")


def _query_terms(query: str, *, max_terms: int) -> list[str]:
    terms: list[str] = []
    for match in _QUERY_TOKEN_RE.finditer(query):
        token = match.group(0)
        normalized = token.casefold() if token.isascii() else token
        if normalized in terms:
            continue
        terms.append(normalized)
        if max_terms and len(terms) >= max_terms:
            break
    return terms


def _evidence_sentences(text: str, *, min_sentence_chars: int) -> list[str]:
    sentences: list[str] = []
    for match in _SENTENCE_RE.finditer(text):
        sentence = (match.group(0)).strip()
        if not sentence:
            continue
        if min_sentence_chars and len(sentence) < min_sentence_chars:
            continue
        sentences.append(sentence)
    return sentences


def _pick_evidence_sentences(sentences: list[str], *, terms: list[str], max_sentences: int) -> list[str]:
    ranked: list[tuple[int, int, int]] = []
    for idx, sentence in enumerate(sentences):
        folded = sentence.casefold()
        score = 0
        for term in terms:
            if term:
                score += term.casefold() in folded if term.isascii() else term in sentence
        if score > 0:
            ranked.append((score, len(sentence), idx))
    if not ranked:
        return sentences[:max_sentences]
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    picked_idx = sorted([idx for _, _, idx in ranked[:max_sentences]])
    return [sentences[index] for index in picked_idx]


def extract_evidence_text(
    text: str,
    query: str,
    *,
    max_chars: int = 0,
    max_sentences: int = 6,
    min_sentence_chars: int = 10,
    max_terms: int = 12,
) -> str:
    """
    Lightweight context compressor: select the most query-relevant sentences/lines.

    This is a heuristic extractor (no LLM). Returns plain text.
    """
    raw = (text).strip()
    if not raw:
        return ""

    max_chars = max(0, int(max_chars))
    max_sentences = max(0, int(max_sentences))
    min_sentence_chars = max(0, int(min_sentence_chars))
    max_terms = max(0, int(max_terms))

    if max_chars and len(raw) <= max_chars:
        return raw
    if max_sentences <= 0:
        return _truncate_with_ellipsis(raw, max_chars=max_chars)

    q = (query).strip()
    if not q:
        return _truncate_with_ellipsis(raw, max_chars=max_chars)

    terms = _query_terms(q, max_terms=max_terms)
    if not terms:
        return _truncate_with_ellipsis(raw, max_chars=max_chars)

    sentences = _evidence_sentences(raw, min_sentence_chars=min_sentence_chars)
    if not sentences:
        return _truncate_with_ellipsis(raw, max_chars=max_chars)

    picked = _pick_evidence_sentences(sentences, terms=terms, max_sentences=max_sentences)
    return _truncate_with_ellipsis("\n".join(picked), max_chars=max_chars)


def find_previous_sentence_boundary(text: str, *, start: int, end: int) -> int:
    """Return the last sentence-boundary position in [start, end), or -1."""
    best = -1
    for ch in _SENTENCE_BOUNDARIES:
        pos = text.rfind(ch, start, end)
        if pos > best:
            best = pos
    return best


def find_next_sentence_boundary(text: str, *, start: int, end: int) -> int | None:
    """Return the first sentence-boundary position in [start, end), or None."""
    best: int | None = None
    for ch in _SENTENCE_BOUNDARIES:
        pos = text.find(ch, start, end)
        if pos < 0:
            continue
        if best is None or pos < best:
            best = pos
    return best


__all__ = [
    "raw_index_from_casefold_index",
    "extract_evidence_text",
    "find_previous_sentence_boundary",
    "find_next_sentence_boundary",
]
