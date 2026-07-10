"""
Lightweight language/script detection helpers.

This module is intentionally dependency-free and conservative:
- It only distinguishes between mainly-CJK vs mainly-Latin vs mixed/unknown.
- It is used for metadata/enrichment (not for semantic rewriting).
"""


import re
from dataclasses import dataclass

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class LanguageDetectResult:
    language: str  # zh | en | mixed | unknown
    cjk_chars: int
    latin_chars: int
    confidence: float


def detect_language(text: str, *, min_chars: int = 40) -> LanguageDetectResult:
    """
    Best-effort language detection for governance metadata.

    Returns:
        - language: "zh" (mostly CJK), "en" (mostly Latin), "mixed", or "unknown"
        - confidence: 0..1 based on dominant-script ratio
    """
    raw = (text or "").strip()
    if not raw:
        return LanguageDetectResult(language="unknown", cjk_chars=0, latin_chars=0, confidence=0.0)

    cjk = len(_CJK_RE.findall(raw))
    latin = len(_LATIN_RE.findall(raw))
    total = cjk + latin
    if total <= 0:
        return LanguageDetectResult(language="unknown", cjk_chars=int(cjk), latin_chars=int(latin), confidence=0.0)

    if total < max(0, int(min_chars or 0)):
        # Too little signal: still report ratio, but call it unknown.
        return LanguageDetectResult(language="unknown", cjk_chars=int(cjk), latin_chars=int(latin), confidence=0.0)

    ratio_cjk = cjk / total
    ratio_latin = latin / total

    if cjk > 0 and latin > 0 and ratio_cjk >= 0.25 and ratio_latin >= 0.25:
        lang = "mixed"
        confidence = 1.0 - abs(ratio_cjk - ratio_latin)
    elif ratio_cjk >= 0.6:
        lang = "zh"
        confidence = ratio_cjk
    elif ratio_latin >= 0.6:
        lang = "en"
        confidence = ratio_latin
    else:
        if cjk > 0 and latin > 0:
            lang = "mixed"
        elif cjk > 0:
            lang = "zh"
        else:
            lang = "en"
        confidence = max(ratio_cjk, ratio_latin)

    return LanguageDetectResult(
        language=str(lang),
        cjk_chars=int(cjk),
        latin_chars=int(latin),
        confidence=float(max(0.0, min(1.0, confidence))),
    )


__all__ = [
    "LanguageDetectResult",
    "detect_language",
]
