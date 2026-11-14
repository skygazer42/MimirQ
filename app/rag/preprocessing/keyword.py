"""
Keyword extraction utilities for governance/reranking.

Supported providers:
- `auto`: use the existing jieba TF-IDF extractor
- `jieba` / `jieba_tfidf`: jieba TF-IDF
- `jieba_textrank`: jieba TextRank
- `simple`: lightweight regex-based fallback
"""

from __future__ import annotations

import re
from collections import Counter
from operator import itemgetter
from typing import Any, cast

from app.core.model_execution import reject_retired_provider
from app.rag.preprocessing.stopwords import STOPWORDS


class UnsupportedKeywordProviderError(ValueError):
    pass


class KeywordProviderUnavailableError(RuntimeError):
    pass


UnsupportedKeywordProvider = UnsupportedKeywordProviderError
KeywordProviderUnavailable = KeywordProviderUnavailableError


_extractor_cache: dict[str, JiebaKeywordTableHandler | JiebaTextRankKeywordExtractor | SimpleKeywordExtractor] = {}
_STOPWORDS_CASEFOLD = {str(s).casefold() for s in STOPWORDS if isinstance(s, str) and s.strip()}


def _expand_tokens_with_subtokens(tokens: set[str]) -> set[str]:
    results: set[str] = set()
    for token in tokens:
        token = str(token).strip()
        if not token:
            continue
        results.add(token)
        sub_tokens = re.findall(r"\w+", token)
        if len(sub_tokens) > 1:
            results.update({w for w in sub_tokens if w.casefold() not in _STOPWORDS_CASEFOLD})
    return results


def get_keyword_extractor(
    provider: str | None = None,
) -> JiebaKeywordTableHandler | JiebaTextRankKeywordExtractor | SimpleKeywordExtractor:
    key = ("jieba" if provider is None else provider).lower().strip()
    reject_retired_provider(key, capability="keyword")
    cached = _extractor_cache.get(key)
    if cached is not None:
        return cached
    if key in {"auto", "jieba", "jieba_tfidf"}:
        extractor = JiebaKeywordTableHandler()
    elif key == "jieba_textrank":
        extractor = JiebaTextRankKeywordExtractor()
    elif key == "simple":
        extractor = SimpleKeywordExtractor()
    else:
        raise UnsupportedKeywordProviderError(f"Unsupported keyword provider: {provider}")
    _extractor_cache[key] = extractor
    return extractor


def extract_keywords(
    text: str,
    *,
    provider: str | None = None,
    top_k: int | None = 10,
    **kwargs: Any,
) -> list[str]:
    extractor = get_keyword_extractor(provider)
    keywords = extractor.extract_keywords(text, max_keywords_per_chunk=top_k, **kwargs)
    return sorted({str(k).strip() for k in keywords if str(k).strip()})


class JiebaKeywordTableHandler:
    """Handler for extracting keywords using Jieba TF-IDF."""

    def __init__(self) -> None:
        tfidf = self._load_tfidf_extractor()
        tfidf.stop_words = STOPWORDS
        self._tfidf = tfidf

    def _load_tfidf_extractor(self) -> Any:
        """Load jieba TFIDF extractor with fallback strategy."""
        import jieba.analyse

        tfidf = getattr(jieba.analyse, "default_tfidf", None)
        if tfidf is not None:
            return tfidf

        tfidf_class = getattr(jieba.analyse, "TFIDF", None)
        if tfidf_class is None:
            try:
                from jieba.analyse.tfidf import TFIDF

                tfidf_class = TFIDF
            except Exception:
                tfidf_class = None

        if tfidf_class is not None:
            tfidf = tfidf_class()
            jieba.analyse.default_tfidf = tfidf
            return tfidf

        return self._build_fallback_tfidf()

    @staticmethod
    def _build_fallback_tfidf() -> Any:
        """Fallback lightweight TFIDF for environments missing jieba's TFIDF."""
        import jieba

        class _SimpleTFIDF:
            def __init__(self) -> None:
                self.stop_words = STOPWORDS
                self._lcut = getattr(jieba, "lcut", None)

            def extract_tags(self, sentence: str, top_k: int | None = 20, **kwargs: Any) -> list[Any]:
                top_k = kwargs.pop("topK", top_k)
                cut = getattr(jieba, "cut", None)
                if self._lcut:
                    tokens = self._lcut(sentence)
                elif callable(cut):
                    tokens = list(cut(sentence))
                else:
                    tokens = re.findall(r"\w+", sentence)

                words = [w for w in tokens if w and w not in self.stop_words]
                freq: dict[str, int] = {}
                for w in words:
                    freq[w] = freq.get(w, 0) + 1

                sorted_words = sorted(freq.items(), key=itemgetter(1), reverse=True)
                if top_k is not None:
                    sorted_words = sorted_words[:top_k]

                return [item[0] for item in sorted_words]

        return _SimpleTFIDF()

    def extract_keywords(self, text: str, max_keywords_per_chunk: int | None = 10) -> set[str]:
        keywords = self._tfidf.extract_tags(
            sentence=text,
            topK=max_keywords_per_chunk,
        )
        keywords = cast(list[str], keywords)
        return _expand_tokens_with_subtokens(set(keywords))


class JiebaTextRankKeywordExtractor:
    """Keyword extractor backed by jieba TextRank."""

    def __init__(self) -> None:
        textrank = self._load_textrank_extractor()
        textrank.stop_words = STOPWORDS
        self._textrank = textrank

    @staticmethod
    def _load_textrank_extractor() -> Any:
        import jieba.analyse

        default = getattr(jieba.analyse, "default_textrank", None)
        if default is not None:
            return default

        cls = getattr(jieba.analyse, "TextRank", None)
        if cls is None:
            try:
                from jieba.analyse.textrank import TextRank

                cls = TextRank
            except Exception:
                cls = None

        if cls is None:
            raise RuntimeError("jieba TextRank is not available")

        instance = cls()
        jieba.analyse.default_textrank = instance
        return instance

    def extract_keywords(self, text: str, max_keywords_per_chunk: int | None = 10) -> set[str]:
        keywords = self._textrank.extract_tags(
            sentence=text,
            topK=max_keywords_per_chunk,
        )
        keywords = cast(list[str], keywords)
        return _expand_tokens_with_subtokens(set(keywords))


class SimpleKeywordExtractor:
    """Very lightweight keyword extractor using regex tokenization + frequency."""

    _TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}")

    def extract_keywords(self, text: str, max_keywords_per_chunk: int | None = 10) -> set[str]:
        raw = (text).strip()
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
        top_k = max_keywords_per_chunk
        ranked = [w for w, _ in counts.most_common(cast(int, top_k))] if top_k else [w for w, _ in counts.most_common()]
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
