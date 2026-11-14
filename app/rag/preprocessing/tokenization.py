"""
Shared lexical tokenization helpers.

These are used across:
- Lexical retrieval and reranking
- Chunk quality and context analysis
- Keyword matching over chat history in the database
"""

import re
import unicodedata
from functools import lru_cache

import jieba

from app.core.config import settings
from app.rag.preprocessing.stopwords import STOPWORDS

_LEXICAL_TOKENIZE_CACHE_MAX_CHARS = 200


@lru_cache(maxsize=4096)
def _tokenize_lexical_text_cached(text: str) -> tuple[str, ...]:
    return tuple(_tokenize_lexical_text_impl(text))


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9][\\A-Za-z0-9_+./:-]*[A-Za-z0-9+]")
_ASCII_PATH_SPLIT_RE = re.compile(r"[\\/]+")
_ASCII_PART_SPLIT_RE = re.compile(r"[_\-.:]+")
_ALNUM_SEGMENT_RE = re.compile(r"[0-9A-Za-z]+")
_NUM_SEQ_RE = re.compile(r"\d{2,}")
_NUM_COMMA_UNDER_RE = re.compile(r"\d[\d,_]{2,}\d")


def _normalize_lexical_text(text: str) -> str:
    """
    Normalize query/doc text before tokenization.

    NFKC is intentionally used to fold full-width Latin/digits into ASCII forms
    (e.g. "ＡＰＩ" -> "API", "２０２６" -> "2026") for multilingual recall stability.
    """

    raw = (text).strip()
    if not raw:
        return ""
    return unicodedata.normalize("NFKC", raw)


def _keep_token(norm: str) -> bool:
    if not norm:
        return False
    if norm in STOPWORDS:
        return False
    # Skip single-character tokens (too noisy for lexical matching).
    if len(norm) < 2:
        return False
    return True


def _split_camel_alnum_segment(segment: str) -> list[str]:
    if not segment:
        return []
    out: list[str] = []
    start = 0
    n = len(segment)
    for idx in range(1, n):
        prev = segment[idx - 1]
        cur = segment[idx]
        nxt = segment[idx + 1] if idx + 1 < n else ""
        # Split on:
        # - lower->upper: "chatRAG" -> "chat", "RAG"
        # - acronym boundary: "HTTPServer" -> "HTTP", "Server"
        # - letter<->digit: "Http2" -> "Http", "2"
        if prev.islower() and cur.isupper():
            out.append(segment[start:idx])
            start = idx
            continue
        if prev.isupper() and cur.isupper() and nxt and nxt.islower():
            out.append(segment[start:idx])
            start = idx
            continue
        if prev.isalpha() and cur.isdigit():
            out.append(segment[start:idx])
            start = idx
            continue
        if prev.isdigit() and cur.isalpha():
            out.append(segment[start:idx])
            start = idx
    out.append(segment[start:])
    return out


def _camel_subtokens(raw_token: str) -> list[str]:
    if not raw_token:
        return []
    out: list[str] = []
    for segment in _ALNUM_SEGMENT_RE.findall(raw_token):
        if not segment:
            continue
        # Require some casing signal to avoid splitting normal lowercase words.
        if not (any(c.islower() for c in segment) and any(c.isupper() for c in segment)):
            continue
        for part in _split_camel_alnum_segment(segment):
            norm = part.strip().casefold()
            if _keep_token(norm):
                out.append(norm)
    return out


def _version_subtokens(norm_token: str) -> list[str]:
    """
    Extract version-like subtokens to reduce false negatives.

    Examples:
      v1.2.3 -> ["1.2.3", "1.2"]
      3.10.0 -> ["3.10.0", "3.10"]
    """
    if not norm_token:
        return []
    # Only consider tokens that look like dotted versions.
    m = re.match(r"^v?(\d+(?:\.\d+){1,6})$", norm_token, flags=re.IGNORECASE)
    if not m:
        return []
    ver = m.group(1)
    parts = ver.split(".")
    out: list[str] = []
    if _keep_token(ver):
        out.append(ver)
    # Add a major.minor prefix when available (helps queries that omit patch).
    if len(parts) >= 2:
        prefix = ".".join(parts[:2])
        if _keep_token(prefix):
            out.append(prefix)
    return out


def _numeric_normalization_tokens(text: str) -> list[str]:
    if not settings.BM25_TOKENIZE_NUMERIC_NORMALIZATION_ENABLED:
        return []
    raw = text
    out: list[str] = []
    # 1) Plain digit sequences (>= 2 chars), e.g. 2024, 42.
    for m in _NUM_SEQ_RE.findall(raw):
        norm = m
        if _keep_token(norm):
            out.append(norm)
    # 2) Comma/underscore separated numbers, e.g. 1,234 or 12_345 -> 1234/12345.
    for m in _NUM_COMMA_UNDER_RE.findall(raw):
        norm = m.replace(",", "").replace("_", "")
        if _keep_token(norm):
            out.append(norm)
    return out


def _append_unique_token(tokens: list[str], seen: set[str], token: str) -> None:
    if not _keep_token(token) or token in seen:
        return
    tokens.append(token)
    seen.add(token)


def _expand_ascii_parts(norm: str, *, tokens: list[str], seen: set[str]) -> None:
    for seg in _ASCII_PATH_SPLIT_RE.split(norm):
        segment = seg.strip()
        if segment and segment != norm:
            _append_unique_token(tokens, seen, segment)
        for part in _ASCII_PART_SPLIT_RE.split(segment):
            _append_unique_token(tokens, seen, part.strip())


def _expand_ascii_subtokens(raw_tok: str, norm: str, *, tokens: list[str], seen: set[str]) -> None:
    _expand_ascii_parts(norm, tokens=tokens, seen=seen)
    for sub in _camel_subtokens(raw_tok):
        _append_unique_token(tokens, seen, sub)
    for sub in _version_subtokens(norm):
        _append_unique_token(tokens, seen, sub)


def _tokenize_ascii_text(text: str) -> list[str]:
    tokens: list[str] = []
    extra: set[str] = set()
    for token in _ASCII_TOKEN_RE.findall(text):
        raw_tok = token.strip()
        if not raw_tok:
            continue
        norm = raw_tok.casefold()
        if not _keep_token(norm):
            continue
        tokens.append(norm)
        # Treat the base token as already emitted so expansion logic doesn't duplicate it.
        extra.add(norm)

        if not settings.BM25_TOKENIZE_ASCII_EXPAND_ENABLED:
            continue
        _expand_ascii_subtokens(raw_tok, norm, tokens=tokens, seen=extra)

    # Add numeric normalization tokens (once per input).
    for n in _numeric_normalization_tokens(text):
        _append_unique_token(tokens, extra, n)

    return tokens


def _append_ascii_tokens(tokens: list[str], cjk_oov_buf: list[str], extra_budget: list[int], text: str) -> None:
    _flush_cjk_oov_buffer(cjk_oov_buf, tokens, extra_budget=extra_budget)
    for token in _tokenize_ascii_text(text):
        if _keep_token(token):
            tokens.append(token)


def _append_cjk_token(tokens: list[str], cjk_oov_buf: list[str], extra_budget: list[int], token: str) -> None:
    _flush_cjk_oov_buffer(cjk_oov_buf, tokens, extra_budget=extra_budget)
    if _keep_token(token):
        tokens.append(token)


def _is_cjk_char(ch: str) -> bool:
    if not ch:
        return False
    o = ord(ch)
    # Basic CJK Unified Ideographs + Extension A.
    return (0x4E00 <= o <= 0x9FFF) or (0x3400 <= o <= 0x4DBF)


def _flush_cjk_oov_buffer(buf: list[str], out_tokens: list[str], *, extra_budget: list[int]) -> None:
    """
    Convert a sequence of single-character CJK tokens into recall-friendly subtokens.

    We keep this as a *fallback* path to avoid exploding the BM25 index size for normal text.
    """
    if not buf:
        return
    s = "".join(buf)
    buf.clear()

    if not settings.BM25_TOKENIZE_CJK_OOV_BIGRAM_ENABLED:
        return

    max_term_chars = settings.BM25_TOKENIZE_CJK_OOV_MAX_TERM_CHARS
    if 2 <= len(s) <= max_term_chars and _keep_token(s):
        out_tokens.append(s)
        extra_budget[0] = max(0, extra_budget[0] - 1)
        if extra_budget[0] <= 0:
            return

    # Add character bigrams: "量子纠缠" -> ["量子", "子纠", "纠缠"].
    for i in range(0, max(0, len(s) - 1)):
        if extra_budget[0] <= 0:
            break
        bg = s[i : i + 2]
        if _keep_token(bg):
            out_tokens.append(bg)
            extra_budget[0] = max(0, extra_budget[0] - 1)


def _tokenize_lexical_text_impl(text: str) -> list[str]:
    raw = _normalize_lexical_text(text)
    if not raw:
        return []

    if raw.isascii():
        return _tokenize_ascii_text(raw)

    tokens: list[str] = []
    # Keep a small expansion budget to avoid pathological token explosion on weird inputs.
    extra_budget = [settings.BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS]
    cjk_oov_buf: list[str] = []

    for token in jieba.cut_for_search(raw):
        tok = str(token).strip()
        if not tok:
            continue

        # Let the shared ASCII tokenizer handle all technical tokens uniformly (paths, versions, ids).
        if tok.isascii():
            _append_ascii_tokens(tokens, cjk_oov_buf, extra_budget, tok)
            continue

        # Build CJK bigram fallback only for OOV-like sequences where jieba yields single chars.
        if len(tok) == 1 and _is_cjk_char(tok):
            cjk_oov_buf.append(tok)
            # Avoid unbounded growth if jieba emits a long stream of single chars.
            if len(cjk_oov_buf) >= 64:
                _flush_cjk_oov_buffer(cjk_oov_buf, tokens, extra_budget=extra_budget)
            continue

        _append_cjk_token(tokens, cjk_oov_buf, extra_budget, tok)

    _flush_cjk_oov_buffer(cjk_oov_buf, tokens, extra_budget=extra_budget)

    # Also extract ASCII/numeric tokens from the full mixed text.
    # This catches things like "/api/v1" that may be adjacent to CJK and not surfaced by jieba reliably.
    tokens.extend(_tokenize_ascii_text(raw))
    return tokens


def tokenize_lexical_text(text: str) -> list[str]:
    """
    Tokenize text for lexical matching and analysis.

    Notes:
    - Uses jieba search mode.
    - Applies conservative filters: stopwords, empty tokens, single-character tokens.
    """
    raw = _normalize_lexical_text(text)
    if not raw:
        return []
    # Cache only short strings (queries, titles) to avoid unbounded memory use.
    if len(raw) <= _LEXICAL_TOKENIZE_CACHE_MAX_CHARS:
        return list(_tokenize_lexical_text_cached(raw))
    return _tokenize_lexical_text_impl(raw)


def warmup_lexical_tokenizer() -> None:
    """Pay the per-process Jieba initialization cost before serving traffic."""
    jieba.initialize()
    tokenize_lexical_text("MimirQ knowledge retrieval 知识库检索预热")
