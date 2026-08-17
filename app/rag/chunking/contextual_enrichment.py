
import re
from collections import Counter

from app.rag.preprocessing.tokenization import tokenize_for_bm25

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# Very small stoplists: goal is to avoid obviously useless tokens, not to be perfect.
_STOPWORDS_EN = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "as",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "from",
        "at",
        "into",
        "not",
    }
)

_STOPWORDS_ZH = frozenset(
    {
        "的",
        "了",
        "和",
        "与",
        "及",
        "或",
        "在",
        "对",
        "是",
        "有",
        "无",
        "为",
        "本",
        "该",
        "此",
        "上述",
        "以下",
        "以上",
        "这里",
        "那里",
    }
)


def _is_mostly_cjk(text: str) -> bool:
    raw = str(text or "")
    if not raw:
        return False
    try:
        cjk = len(_CJK_RE.findall(raw))
    except Exception:
        return False
    return (cjk / max(1, len(raw))) >= 0.12


def _extract_section(meta: dict) -> str | None:
    if not isinstance(meta, dict):
        return None
    header = meta.get("header_path") or meta.get("outline_path_str") or meta.get("header_context")
    if isinstance(header, str) and header.strip():
        return header.strip()[:160]

    header_list = meta.get("outline_path") or meta.get("header_path_list")
    if isinstance(header_list, list) and header_list:
        parts = [str(x).strip() for x in header_list if str(x).strip()]
        if parts:
            return " / ".join(parts[:10])[:160]
    return None


def _extract_keywords(content: str, *, top_k: int, max_chars: int) -> list[str]:
    text = str(content or "").strip()
    if not text:
        return []
    sample = text[: max(0, int(max_chars or 0))] if max_chars else text

    tokens = tokenize_for_bm25(sample)
    if not tokens:
        return []

    mostly_cjk = _is_mostly_cjk(sample)
    stop = _STOPWORDS_ZH if mostly_cjk else _STOPWORDS_EN
    filtered: list[str] = []
    for t in tokens:
        tok = str(t or "").strip()
        if not tok:
            continue
        if len(tok) <= 1:
            continue
        if tok.lower() in stop:
            continue
        filtered.append(tok)

    if not filtered:
        return []

    counts = Counter(filtered)
    out: list[str] = []
    for tok, _n in counts.most_common(max(0, int(top_k or 0))):
        tok_norm = str(tok).strip()
        if not tok_norm:
            continue
        out.append(tok_norm[:40])
    return out


def _build_intro_part(*, title: str, mostly_cjk: bool) -> str:
    if title:
        return f"本文档《{title}》的摘录。" if mostly_cjk else f"Excerpt from document '{title}'."
    return "本文档摘录。" if mostly_cjk else "Document excerpt."


def _build_section_part(section: str | None, *, mostly_cjk: bool) -> str | None:
    if not section:
        return None
    return f"章节：{section}。" if mostly_cjk else f"Section: {section}."


def _build_keywords_part(keywords: list[str], *, mostly_cjk: bool) -> str | None:
    if not keywords:
        return None
    joined = "，".join(keywords) if mostly_cjk else ", ".join(keywords)
    return f"关键词：{joined}。" if mostly_cjk else f"Keywords: {joined}."


def _cap_prefix(prefix: str, *, max_prefix_chars: int, mostly_cjk: bool) -> str:
    cap = max(40, int(max_prefix_chars or 0))
    if len(prefix) <= cap:
        return prefix
    capped = prefix[:cap].rstrip()
    if capped.endswith((".", "。", "!", "！")):
        return capped
    if len(capped) >= cap:
        capped = capped[: max(0, cap - 1)].rstrip()
    return capped + ("。" if mostly_cjk else ".")


def build_context_prefix(
    content: str,
    *,
    document_title: str | None,
    meta: dict,
    max_prefix_chars: int = 240,
    keywords_top_k: int = 6,
    keywords_max_chars: int = 2000,
) -> str | None:
    """
    Best-effort contextual retrieval prefix.

    Design goals:
    - No LLM calls (cheap, deterministic).
    - Avoid copying large raw content into the prefix.
    - Keep it short and bounded (stable embeddings).
    """
    body = str(content or "").strip()
    if not body:
        return None

    title = str(document_title or "").strip()
    section = _extract_section(meta)
    keywords = _extract_keywords(body, top_k=int(keywords_top_k or 0), max_chars=int(keywords_max_chars or 0))

    mostly_cjk = _is_mostly_cjk(body)

    parts = [
        _build_intro_part(title=title, mostly_cjk=mostly_cjk),
        _build_section_part(section, mostly_cjk=mostly_cjk),
        _build_keywords_part(keywords, mostly_cjk=mostly_cjk),
    ]

    prefix = " ".join([p for p in parts if p]).strip()
    if not prefix:
        return None
    return _cap_prefix(prefix, max_prefix_chars=max_prefix_chars, mostly_cjk=mostly_cjk)


__all__ = ["build_context_prefix"]
