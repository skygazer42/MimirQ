"""
Alias / canonicalization heuristics for KG extraction.

Goal: reduce entity fragmentation across documents (e.g. "Retrieval-Augmented Generation" vs "RAG")
by detecting explicit alias definitions in text and generating:
- canonical surface forms (strip trailing "(ABBR)")
- alias entities (ABBR)
- alias relations (alias_of)

This is intentionally conservative: it only fires on explicit patterns (parentheses, "简称/aka")
and should prefer precision over recall.
"""


import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class AliasCandidate:
    """
    A raw alias definition observed in text.

    `a` and `b` are the two surface forms found together (unordered).
    """

    a: str
    b: str
    method: str = "unknown"
    # Best-effort evidence snippet (matched substring from the source text).
    quote: str | None = None


_WS_RE = re.compile(r"\s+")
_EDGE_PUNCT_CHARS = "\"'`“”‘’"
_EN_CONNECTOR_WORDS = {
    # Keep this list short and conservative; it's only used to trim
    # leading context for patterns like "X of Y (ABBR)".
    "of",
    "and",
    "or",
    "for",
    "to",
    "in",
    "on",
    "the",
    "a",
    "an",
    # Common name particles (best-effort).
    "de",
    "la",
    "le",
    "von",
    "der",
    "da",
    "di",
    "del",
    "du",
}

# (Long Form) (Short Form) pair anywhere in text.
_PARENS_RE = re.compile(
    r"(?P<long>[^()（）\n]{2,80}?)\s*[（(]\s*(?P<short>[^()（）\n]{2,40}?)\s*[)）]",
    flags=re.UNICODE,
)

# Chinese "简称/又称/以下简称" patterns. Keep fairly strict to avoid runaway captures.
_ZH_ABBR_RE = re.compile(
    r"(?P<long>[^，。,；;()\n]{2,80}?)\s*(?:，|,)?\s*(?:简称|又称|也称|下称|以下简称|简称为)\s*"
    r"[\"'“”‘’]*?(?P<short>[^\"'“”‘’，。,；;()\n]{2,20})",
    flags=re.UNICODE,
)

# English "aka/also known as" patterns (conservative).
_EN_AKA_RE = re.compile(
    r"(?P<long>[^,;()\n]{2,80}?)\s*(?:,|\()?\s*(?:aka|a\\.k\\.a\\.|also known as)\s*"
    r"[\"'“”‘’]*?(?P<short>[^\"'“”‘’，。,；;()\n]{2,20})",
    flags=re.IGNORECASE | re.UNICODE,
)

_VERSION_LIKE_RE = re.compile(r"^(?:v|ver|version)?\d+(?:\.\d+){0,3}$", flags=re.IGNORECASE)
_CJK_NON_ABBREV_SUFFIXES: tuple[str, ...] = (
    # Organization / institution suffixes (common in Chinese full names).
    "有限责任公司",
    "股份有限公司",
    "有限公司",
    "集团公司",
    "集团",
    "公司",
    "大学",
    "学院",
    "研究院",
    "研究所",
    "科学院",
    "委员会",
    "办公室",
    "中心",
    "实验室",
    "医院",
    "银行",
    "协会",
    "基金会",
    "政府",
)


def _clean_surface(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = _WS_RE.sub(" ", s).strip()
    s = s.strip(_EDGE_PUNCT_CHARS).strip()
    return s


def _contains_cjk(text: str) -> bool:
    for ch in str(text or ""):
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:
            return True
    return False


def _is_all_cjk(text: str) -> bool:
    s = str(text or "")
    if not s:
        return False
    for ch in s:
        code = ord(ch)
        if not (0x4E00 <= code <= 0x9FFF):
            return False
    return True


def _is_en_term_token(token: str) -> bool:
    """
    A conservative heuristic: treat tokens as part of an English "term" if they
    look like proper nouns / abbreviations / versioned names.
    """
    t = str(token or "").strip()
    if not t:
        return False
    if any(ch.isupper() for ch in t):
        return True
    if any(ch.isdigit() for ch in t):
        return True
    if any(ch in "-._+/:" for ch in t):
        return True
    if t.isalpha() and t.isupper():
        return True
    return False


def _trim_long_surface_parentheses(text: str) -> str:
    """
    `_PARENS_RE` is intentionally permissive and can capture leading context:
    e.g. "We use Retrieval-Augmented Generation (RAG)".

    This tries to recover the nearest "term-like" suffix before the parentheses
    so the result can match extracted entity surfaces.
    """
    s = _clean_surface(text)
    if not s:
        return s
    if " " not in s:
        return s

    parts = [p for p in s.split(" ") if p]
    if not parts:
        return s

    kept_rev: list[str] = []
    saw_term = False
    for tok in reversed(parts):
        low = tok.casefold()
        if low in _EN_CONNECTOR_WORDS and saw_term:
            kept_rev.append(tok)
            continue
        if _is_en_term_token(tok):
            kept_rev.append(tok)
            saw_term = True
            continue
        break

    if not kept_rev:
        return s

    kept_rev.reverse()
    trimmed = " ".join(kept_rev).strip()
    # Guardrail: don't replace with something extremely short (likely noise).
    if len(trimmed) < 2:
        return s
    return trimmed


def best_suffix_match(text: str, candidates: list[str], *, min_chars: int = 2) -> str | None:
    """
    Return the longest candidate string that is a suffix of `text`.

    Used as a best-effort alignment mechanism when regex extraction captures
    leading context (common in CJK where spaces are absent).
    """
    t = _clean_surface(text).casefold()
    if not t:
        return None

    best: str | None = None
    lim = max(0, int(min_chars or 0))
    if lim <= 0:
        lim = 1

    for cand in candidates or []:
        c = _clean_surface(str(cand or "")).casefold()
        if not c or len(c) < lim:
            continue
        if not t.endswith(c):
            continue
        if best is None or len(c) > len(best):
            best = c

    return best


def looks_like_version_token(text: str) -> bool:
    s = _clean_surface(text)
    if not s:
        return False
    if _VERSION_LIKE_RE.match(s):
        return True
    # Common release labels.
    if s.casefold() in {"rc", "alpha", "beta"}:
        return True
    return False


def is_abbrev_token(text: str) -> bool:
    """
    Heuristic for abbreviation/alias tokens.

    Examples:
    - "RAG", "LLM", "THU", "GPT-4", "DeepSeekV3"
    - Chinese short forms are allowed (2-4 chars) but full-name suffixes are excluded
      (e.g. "清华大学", "微软公司").
    """
    s = _clean_surface(text)
    if not s:
        return False
    if " " in s:
        return False
    if looks_like_version_token(s):
        return False

    if _contains_cjk(s):
        # High precision: only treat *pure* CJK tokens as CJK abbreviations.
        if not _is_all_cjk(s):
            return False
        # Most Chinese abbreviations are 2-4 characters (e.g. 清华/北航/中科院).
        if len(s) < 2 or len(s) > 4:
            return False
        # Common full-name suffixes should not be treated as abbreviations.
        for suf in _CJK_NON_ABBREV_SUFFIXES:
            if s.endswith(suf):
                return False
        return True

    # ASCII-ish abbreviations.
    if len(s) < 2 or len(s) > 15:
        return False
    if s.isdigit():
        return False

    # Allow a compact set of characters typical for abbreviations.
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._+/")
    if any(ch not in allowed for ch in s):
        return False

    # Require at least one letter (avoid pure symbol/digit tokens).
    if not any(ch.isalpha() for ch in s):
        return False

    # Pure alphabetic tokens are only treated as abbreviations when ALL CAPS.
    # This keeps precision high (avoid treating regular words like "Foo" as abbreviations).
    if s.isalpha():
        return s.isupper()

    # Mixed tokens (digits/punct) are allowed (e.g. GPT-4, DeepSeekV3).
    return True


def choose_alias_direction(a: str, b: str) -> tuple[str, str] | None:
    """
    Decide which surface is alias vs canonical.

    Returns (alias_surface, canonical_surface) or None if not confident.
    """
    a_clean = _clean_surface(a)
    b_clean = _clean_surface(b)
    if not a_clean or not b_clean:
        return None
    if a_clean.casefold() == b_clean.casefold():
        return None

    a_abbrev = is_abbrev_token(a_clean)
    b_abbrev = is_abbrev_token(b_clean)

    if a_abbrev and not b_abbrev:
        return a_clean, b_clean
    if b_abbrev and not a_abbrev:
        return b_clean, a_clean

    # If both (or neither) look like abbreviations, skip to preserve precision.
    return None


def extract_alias_candidates(text: str, *, max_candidates: int = 20) -> list[AliasCandidate]:
    """
    Extract explicit alias candidates from text.

    This returns unordered pairs (a, b). Direction (alias vs canonical) is decided later.
    """
    clean = unicodedata.normalize("NFKC", str(text or ""))
    if not clean:
        return []

    lim = max(0, int(max_candidates or 0))
    if lim <= 0:
        return []

    out: list[AliasCandidate] = []
    seen: set[tuple[str, str, str]] = set()

    def _push_with_quote(a: str, b: str, method: str, *, quote: str | None) -> None:
        if len(out) >= lim:
            return
        a2 = _clean_surface(a)
        if method == "parentheses":
            a2 = _trim_long_surface_parentheses(a2)
        b2 = _clean_surface(b)
        if not a2 or not b2:
            return
        if a2.casefold() == b2.casefold():
            return
        key = tuple(sorted([a2.casefold(), b2.casefold()])) + (method,)
        if key in seen:
            return
        seen.add(key)
        q = _clean_surface(quote or "") if quote else None
        if q:
            q = q[:240]
        out.append(AliasCandidate(a=a2, b=b2, method=method, quote=q))

    for m in _PARENS_RE.finditer(clean):
        _push_with_quote(m.group("long"), m.group("short"), method="parentheses", quote=m.group(0))
        if len(out) >= lim:
            break

    if len(out) < lim:
        for m in _ZH_ABBR_RE.finditer(clean):
            _push_with_quote(m.group("long"), m.group("short"), method="zh_abbr", quote=m.group(0))
            if len(out) >= lim:
                break

    if len(out) < lim:
        for m in _EN_AKA_RE.finditer(clean):
            _push_with_quote(m.group("long"), m.group("short"), method="en_aka", quote=m.group(0))
            if len(out) >= lim:
                break

    return out


def split_trailing_parenthetical_alias(name: str) -> tuple[str, str] | None:
    """
    If `name` looks like "Long (Short)" return (Long, Short). Otherwise None.
    """
    raw = _clean_surface(name)
    if not raw:
        return None

    # Parse a trailing parenthetical without regex to avoid S5852 hotspots.
    # Accept both ASCII and fullwidth parentheses.
    s = raw.strip()
    if not s or s[-1] not in (")", "）"):
        return None

    close = s[-1]
    open_idx_ascii = s.rfind("(", 0, len(s) - 1)
    open_idx_full = s.rfind("（", 0, len(s) - 1)
    open_idx = max(open_idx_ascii, open_idx_full)
    if open_idx < 0:
        return None

    open_ch = s[open_idx]
    if open_ch == "(" and close != ")":
        return None
    if open_ch == "（" and close != "）":
        return None

    head_raw = s[:open_idx].strip()
    tail_raw = s[open_idx + 1 : -1].strip()

    # Keep tail bounded and exclude nested parentheses/newlines to reduce noise.
    if not head_raw or not tail_raw:
        return None
    if not (2 <= len(tail_raw) <= 40):
        return None
    if any(ch in "()（）\n\r" for ch in tail_raw):
        return None

    head = _clean_surface(head_raw)
    tail = _clean_surface(tail_raw)
    if not head or not tail:
        return None
    if head.casefold() == tail.casefold():
        return None
    return head, tail


__all__ = [
    "AliasCandidate",
    "best_suffix_match",
    "choose_alias_direction",
    "extract_alias_candidates",
    "is_abbrev_token",
    "looks_like_version_token",
    "split_trailing_parenthetical_alias",
]
