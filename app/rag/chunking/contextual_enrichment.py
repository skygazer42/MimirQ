
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

    parts: list[str] = []
    if title:
        if mostly_cjk:
            parts.append(f"本文档《{title}》的摘录。")
        else:
            parts.append(f"Excerpt from document '{title}'.")
    else:
        if mostly_cjk:
            parts.append("本文档摘录。")
        else:
            parts.append("Document excerpt.")

    if section:
        if mostly_cjk:
            parts.append(f"章节：{section}。")
        else:
            parts.append(f"Section: {section}.")

    if keywords:
        joined = "，".join(keywords) if mostly_cjk else ", ".join(keywords)
        if mostly_cjk:
            parts.append(f"关键词：{joined}。")
        else:
            parts.append(f"Keywords: {joined}.")

    prefix = " ".join([p for p in parts if p]).strip()
    if not prefix:
        return None

    cap = max(40, int(max_prefix_chars or 0))
    if len(prefix) > cap:
        prefix = prefix[:cap].rstrip()
        if not prefix.endswith((".", "。", "!", "！")):
            if len(prefix) >= cap:
                prefix = prefix[: max(0, cap - 1)].rstrip()
            prefix = prefix + ("。" if mostly_cjk else ".")

    return prefix


__all__ = ["build_context_prefix"]
