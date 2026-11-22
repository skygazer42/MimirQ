"""
Keyword extraction utilities for governance/reranking.

Supported providers:
- `auto`: use the existing jieba TF-IDF extractor
- `jieba` / `jieba_tfidf`: jieba TF-IDF
- `jieba_textrank`: jieba TextRank
- `simple`: lightweight regex-based fallback
"""

import re
from collections import Counter

from app.infrastructure.model_policy import reject_retired_provider
from app.rag.ingestion.governance.text.stopwords import STOPWORDS


class UnsupportedKeywordProviderError(ValueError):
    pass


class KeywordProviderUnavailableError(RuntimeError):
    pass


UnsupportedKeywordProvider = UnsupportedKeywordProviderError
KeywordProviderUnavailable = KeywordProviderUnavailableError


_extractor_cache: "dict[str, JiebaKeywordTableHandler | JiebaTextRankKeywordExtractor | SimpleKeywordExtractor]" = {}
_STOPWORDS_CASEFOLD = {word.casefold() for word in STOPWORDS}


def _expand_tokens_with_subtokens(tokens: set[str]) -> set[str]:
    results: set[str] = set()
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        results.add(token)
        sub_tokens = re.findall(r"\w+", token)
        if len(sub_tokens) > 1:
            results.update({w for w in sub_tokens if w.casefold() not in _STOPWORDS_CASEFOLD})
    return results


def get_keyword_extractor(
    provider: str | None = None,
) -> "JiebaKeywordTableHandler | JiebaTextRankKeywordExtractor | SimpleKeywordExtractor":
    key = ("jieba" if provider is None else provider).lower().strip()
    reject_retired_provider(key, capability="keyword")
    if key in {"auto", "jieba_tfidf"}:
        key = "jieba"
    cached = _extractor_cache.get(key)
    if cached is not None:
        return cached
    try:
        if key == "jieba":
            extractor = JiebaKeywordTableHandler()
        elif key == "jieba_textrank":
            extractor = JiebaTextRankKeywordExtractor()
        elif key == "simple":
            extractor = SimpleKeywordExtractor()
        else:
            raise UnsupportedKeywordProviderError(f"Unsupported keyword provider: {provider}")
    except ImportError as exc:
        raise KeywordProviderUnavailableError("The configured jieba keyword provider is not installed") from exc
    _extractor_cache[key] = extractor
    return extractor


def extract_keywords(
    text: str,
    *,
    provider: str | None = None,
    top_k: int | None = 10,
) -> list[str]:
    extractor = get_keyword_extractor(provider)
    keywords = extractor.extract_keywords(text, max_keywords_per_chunk=top_k)
    return sorted({word.strip() for word in keywords if word.strip()})


class JiebaKeywordTableHandler:
    """Handler for extracting keywords using Jieba TF-IDF."""

    def __init__(self) -> None:
        from jieba.analyse import default_tfidf

        self._tfidf = default_tfidf
        self._tfidf.stop_words = STOPWORDS

    def extract_keywords(self, text: str, max_keywords_per_chunk: int | None = 10) -> set[str]:
        keywords = self._tfidf.extract_tags(
            sentence=text,
            topK=max_keywords_per_chunk,
        )
        return _expand_tokens_with_subtokens(set(keywords))


class JiebaTextRankKeywordExtractor:
    """Keyword extractor backed by jieba TextRank."""

    def __init__(self) -> None:
        from jieba.analyse import default_textrank

        self._textrank = default_textrank
        self._textrank.stop_words = STOPWORDS

    def extract_keywords(self, text: str, max_keywords_per_chunk: int | None = 10) -> set[str]:
        keywords = self._textrank.extract_tags(
            sentence=text,
            topK=max_keywords_per_chunk,
        )
        return _expand_tokens_with_subtokens(set(keywords))


class SimpleKeywordExtractor:
    """Very lightweight keyword extractor using regex tokenization + frequency."""

    _TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}")

    def extract_keywords(self, text: str, max_keywords_per_chunk: int | None = 10) -> set[str]:
        raw = text.strip()
        if not raw:
            return set()

        tokens = []
        for match in self._TOKEN_RE.finditer(raw):
            token = match.group(0).strip()
            if not token:
                continue
            token_cf = token.casefold()
            if token_cf in _STOPWORDS_CASEFOLD:
                continue
            tokens.append(token_cf if token.isascii() else token)

        if not tokens:
            return set()

        counts = Counter(tokens)
        # Match jieba's existing contract: None and 0 both mean no item limit.
        count = None if max_keywords_per_chunk == 0 else max_keywords_per_chunk
        ranked = [word for word, _ in counts.most_common(count)]
        return set(ranked)


__all__ = [
    "JiebaTextRankKeywordExtractor",
    "JiebaKeywordTableHandler",
    "KeywordProviderUnavailable",
    "STOPWORDS",
    "UnsupportedKeywordProvider",
    "SimpleKeywordExtractor",
    "extract_keywords",
    "get_keyword_extractor",
]
