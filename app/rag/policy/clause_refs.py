
import re

_CN_ARTICLE = re.compile(r"(第[0-9一二三四五六七八九十百千]+条)")
_CN_CLAUSE = re.compile(r"([（(][0-9一二三四五六七八九十]+[)）])")
_EN_ARTICLE = re.compile(r"\barticle\s+\d{1,4}\b", flags=re.IGNORECASE)
_EN_SECTION = re.compile(
    r"\bsection\s+\d{1,4}(?:\.\d{1,4}){0,4}\b",
    flags=re.IGNORECASE,
)


def normalize_clause_ref(ref: str) -> str:
    """
    Normalize a clause reference to a stable, user-friendly format.

    - Trims whitespace
    - Canonicalizes English prefixes ("ARTICLE" -> "Article", "SECTION" -> "Section")
    - Leaves non-ASCII / CN refs unchanged beyond trimming
    """
    s = (ref or "").strip()
    if not s:
        return ""

    low = s.lower()
    if low.startswith("article"):
        parts = s.split(None, 1)
        if len(parts) == 2:
            return "Article " + parts[1].strip()
        return "Article"
    if low.startswith("section"):
        parts = s.split(None, 1)
        if len(parts) == 2:
            return "Section " + parts[1].strip()
        return "Section"

    return s


def extract_clause_refs(text: str) -> list[str]:
    """
    Extract best-effort clause/article/section markers from a free-form query.

    This is intentionally deterministic and auditable:
    - No LLM calls
    - No external dependencies
    - Bounded output (dedup only; caller can cap if needed)
    """
    raw = (text or "").strip()
    if not raw:
        return []

    out: list[str] = []
    seen: set[str] = set()

    def _add(x: str) -> None:
        v = normalize_clause_ref(x)
        if not v:
            return
        key = v.casefold() if v.isascii() else v
        if key in seen:
            return
        seen.add(key)
        out.append(v)

    for m in _CN_ARTICLE.finditer(raw):
        _add(m.group(1))
    for m in _CN_CLAUSE.finditer(raw):
        _add(m.group(1))
    for m in _EN_ARTICLE.finditer(raw):
        _add(m.group(0))
    for m in _EN_SECTION.finditer(raw):
        _add(m.group(0))

    return out

