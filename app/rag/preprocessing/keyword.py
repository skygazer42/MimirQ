"""
Keyword extraction utilities for governance/reranking.

Supported providers:
- `auto`: prefer HanLP if available, else jieba
- `jieba` / `jieba_tfidf`: jieba TF-IDF
- `jieba_textrank`: jieba TextRank
- `hanlp`: HanLP tokenizer + TF (optional dependency)
- `simple`: lightweight regex-based fallback
"""


import importlib.util
import os
import re
from collections import Counter
from collections.abc import Iterable
from operator import itemgetter
from threading import Lock
from typing import Any, cast

from app.rag.preprocessing.stopwords import STOPWORDS


class UnsupportedKeywordProviderError(ValueError):
    pass


class KeywordProviderUnavailableError(RuntimeError):
    pass


UnsupportedKeywordProvider = UnsupportedKeywordProviderError
KeywordProviderUnavailable = KeywordProviderUnavailableError


_extractor_cache: dict[str, object] = {}
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


def get_keyword_extractor(provider: str | None = None) -> object:
    key = (provider or "jieba").lower().strip()
    cached = _extractor_cache.get(key)
    if cached is not None:
        return cached

    extractor: object
    if key in {"jieba", "jieba_tfidf"}:
        extractor = JiebaKeywordTableHandler()
    elif key in {"jieba_textrank"}:
        extractor = JiebaTextRankKeywordExtractor()
    elif key in {"simple"}:
        extractor = SimpleKeywordExtractor()
    elif key == "hanlp":
        extractor = HanLPKeywordExtractor()
    elif key == "auto":
        if importlib.util.find_spec("hanlp") is not None:
            try:
                extractor = HanLPKeywordExtractor()
            except Exception:
                extractor = JiebaKeywordTableHandler()
        else:
            extractor = JiebaKeywordTableHandler()
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
    provider_key = (provider or "jieba").lower().strip()
    extractor = get_keyword_extractor(provider_key)
    if not hasattr(extractor, "extract_keywords"):
        raise KeywordProviderUnavailableError(f"Invalid keyword extractor for provider={provider!r}")
    try:
        keywords = extractor.extract_keywords(text or "", max_keywords_per_chunk=top_k, **kwargs)
    except Exception as exc:  # pragma: no cover
        if provider_key == "hanlp":
            raise KeywordProviderUnavailableError(str(exc) or "HanLP provider failed") from exc
        raise
    return sorted({str(k).strip() for k in (keywords or []) if str(k).strip()})


class JiebaKeywordTableHandler:
    """Handler for extracting keywords using Jieba TF-IDF."""

    def __init__(self):
        tfidf = self._load_tfidf_extractor()
        tfidf.stop_words = STOPWORDS
        self._tfidf = tfidf

    def _load_tfidf_extractor(self):
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
    def _build_fallback_tfidf():
        """Fallback lightweight TFIDF for environments missing jieba's TFIDF."""
        import jieba

        class _SimpleTFIDF:
            def __init__(self):
                self.stop_words = STOPWORDS
                self._lcut = getattr(jieba, "lcut", None)

            def extract_tags(self, sentence: str, top_k: int | None = 20, **kwargs):
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
        return set(_expand_tokens_with_subtokens(set(keywords)))


class JiebaTextRankKeywordExtractor:
    """Keyword extractor backed by jieba TextRank."""

    def __init__(self):
        textrank = self._load_textrank_extractor()
        textrank.stop_words = STOPWORDS
        self._textrank = textrank

    @staticmethod
    def _load_textrank_extractor():
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
        return set(_expand_tokens_with_subtokens(set(keywords)))


class SimpleKeywordExtractor:
    """Very lightweight keyword extractor using regex tokenization + frequency."""

    _TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}")

    def extract_keywords(self, text: str, max_keywords_per_chunk: int | None = 10) -> set[str]:
        raw = (text or "").strip()
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
        top_k = max_keywords_per_chunk if max_keywords_per_chunk is not None else None
        ranked = (
            [w for w, _ in counts.most_common(cast(int, top_k))]
            if top_k
            else [w for w, _ in counts.most_common()]
        )
        return set(ranked)


def _normalize_hanlp_tokens(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        return _normalize_hanlp_string(value)

    if isinstance(value, list):
        return _normalize_hanlp_list(value)

    if isinstance(value, dict):
        return _normalize_hanlp_dict(value)

    return []


def _normalize_hanlp_string(value: str) -> list[str]:
    parts = [p.strip() for p in value.split() if p.strip()]
    if parts:
        return parts
    stripped = value.strip()
    return [stripped] if stripped else []


def _normalize_hanlp_list(value: list[Any]) -> list[str]:
    out: list[str] = []
    for item in value:
        if item is None:
            continue
        if isinstance(item, str):
            token = item.strip()
        else:
            token = str(item).strip()
        if token:
            out.append(token)
    return out


def _normalize_hanlp_dict(value: dict[str, Any]) -> list[str]:
    for key in ("tok", "tok/coarse", "tok/fine"):
        if key in value:
            return _normalize_hanlp_tokens(value.get(key))
    for item in value.values():
        if isinstance(item, (list, str)):
            tokens = _normalize_hanlp_tokens(item)
            if tokens:
                return tokens
    return []


def _filter_tokens(tokens: Iterable[str]) -> list[str]:
    output: list[str] = []
    for raw in tokens:
        token = (raw or "").strip()
        if not token:
            continue
        lower = token.casefold()
        if lower in _STOPWORDS_CASEFOLD:
            continue
        if re.fullmatch(r"\d+", token):
            continue
        if re.fullmatch(r"[\W_]+", token):
            continue
        if len(token) == 1 and not token.isascii():
            continue
        output.append(token)
    return output


class HanLPKeywordExtractor:
    def __init__(self, tokenizer_model: str | None = None) -> None:
        if importlib.util.find_spec("hanlp") is None:
            raise ImportError("HanLP is not installed")

        self._tokenizer_model = tokenizer_model or os.getenv("HANLP_TOKENIZER_MODEL") or ""
        self._tokenizer: Any | None = None
        self._lock = Lock()

    def _ensure_tokenizer(self):
        if self._tokenizer is not None:
            return self._tokenizer

        import hanlp

        candidates: list[str] = []
        if self._tokenizer_model:
            candidates.append(self._tokenizer_model)

        pretrained = getattr(hanlp, "pretrained", None)
        tok = getattr(pretrained, "tok", None) if pretrained is not None else None
        if tok is not None:
            for attr in (
                "COARSE_ELECTRA_SMALL_ZH",
                "FINE_ELECTRA_SMALL_ZH",
                "COARSE_ALBERT_BASE_ZH",
                "FINE_ALBERT_BASE_ZH",
            ):
                model = getattr(tok, attr, None)
                if isinstance(model, str) and model:
                    candidates.append(model)

        candidates.extend(
            [
                "PKU_NAME_MERGED_SIX_MONTHS_CONVSEG",
                "CTB6_CONVSEG",
            ]
        )

        last_exc: Exception | None = None
        for model in candidates:
            try:
                self._tokenizer = hanlp.load(model)
                self._tokenizer_model = model
                return self._tokenizer
            except Exception as exc:  # pragma: no cover
                last_exc = exc
                continue

        raise RuntimeError(
            "HanLP tokenizer model is not available. "
            "Set HANLP_TOKENIZER_MODEL to a valid model identifier."
        ) from last_exc

    def extract_keywords(self, text: str, max_keywords_per_chunk: int | None = 10) -> set[str]:
        raw_text = (text or "").strip()
        if not raw_text:
            return set()

        tokenizer = self._ensure_tokenizer()
        with self._lock:
            result = tokenizer(raw_text)

        tokens = _filter_tokens(_normalize_hanlp_tokens(result))
        if not tokens:
            return set()

        counts = Counter(tokens)
        top_k = max_keywords_per_chunk if max_keywords_per_chunk is not None else None
        ranked = (
            [w for w, _ in counts.most_common(cast(int, top_k))]
            if top_k
            else [w for w, _ in counts.most_common()]
        )
        return set(self._expand_tokens_with_subtokens(set(ranked)))

    @staticmethod
    def _expand_tokens_with_subtokens(tokens: set[str]) -> set[str]:
        return _expand_tokens_with_subtokens(tokens)


__all__ = [
    "HanLPKeywordExtractor",
    "JiebaTextRankKeywordExtractor",
    "JiebaKeywordTableHandler",
    "KeywordProviderUnavailable",
    "STOPWORDS",
    "UnsupportedKeywordProvider",
    "SimpleKeywordExtractor",
    "extract_keywords",
    "get_keyword_extractor",
]
