
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NormalizedQuery:
    normalized_text: str
    applied_rules: list[str]


_RE_NUMERIC_COMMAS = re.compile(r"(?<=\d),(?=\d)")
_RE_VERSION_PREFIX_V = re.compile(r"\bv(?=\d)", flags=re.IGNORECASE)
# Very small, explicit unit normalization (case only) to avoid surprising rewrites.
_RE_UNIT_CASE = re.compile(r"(\d)(\s*)(kb|mb|gb|tb)\b", flags=re.IGNORECASE)
_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "。": ".",
        "，": ",",
        "、": ",",
        "；": ";",
        "：": ":",
        "！": "!",
        "？": "?",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "《": '"',
        "》": '"',
        "〈": '"',
        "〉": '"',
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "—": "-",
        "–": "-",
        "…": "...",
    }
)


def normalize_query(text: str) -> NormalizedQuery:
    """
    Deterministically normalize a query for retrieval.

    Returns both the normalized query and a list of applied rule IDs so callers can
    audit/trace what changed.
    """
    s = str(text or "")
    rules: list[str] = []

    # 1) Full-width/half-width normalization (best-effort ASCII when possible).
    s2 = unicodedata.normalize("NFKC", s)
    if s2 != s:
        rules.append("nfkc")
        s = s2

    # 2) Canonical punctuation shared by queries and indexed retrieval text.
    s2 = s.translate(_PUNCTUATION_TRANSLATION)
    if s2 != s:
        rules.append("punctuation")
        s = s2

    # 3) Path separators (Windows -> POSIX).
    s2 = s.replace("\\", "/")
    if s2 != s:
        rules.append("path_separators")
        s = s2

    # 4) Numbers: remove commas between digits (e.g. 1,000 -> 1000).
    s2 = _RE_NUMERIC_COMMAS.sub("", s)
    if s2 != s:
        rules.append("numeric_commas")
        s = s2

    # 5) Versions: strip leading "v" for version-like tokens (e.g. v1.2.3 -> 1.2.3).
    s2 = _RE_VERSION_PREFIX_V.sub("", s)
    if s2 != s:
        rules.append("version_prefix_v")
        s = s2

    # 6) Unicode-aware case normalization before canonical unit casing.
    s2 = s.casefold()
    if s2 != s:
        rules.append("casefold")
        s = s2

    # 7) Units (limited): canonicalize the unit's letter case only.
    def _unit_repl(m: re.Match[str]) -> str:
        return f"{m.group(1)}{m.group(2)}{m.group(3).upper()}"

    s2 = _RE_UNIT_CASE.sub(_unit_repl, s)
    if s2 != s:
        rules.append("unit_case")
        s = s2

    # 8) Whitespace canonicalization (collapse + strip).
    s2 = " ".join(s.split())
    if s2 != s:
        rules.append("whitespace")
        s = s2

    return NormalizedQuery(normalized_text=s, applied_rules=rules)
