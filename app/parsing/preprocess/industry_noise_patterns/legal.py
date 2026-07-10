
from app.rag.preprocessing.cleaning import RegexRule

RULES: list[RegexRule] = [
    RegexRule(pattern=r"(?m)^\s*本页无正文\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*签署页\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*第\s*\d+\s*页\s*(?:共\s*\d+\s*页)?\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*甲方[:：]\s*签字.*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*乙方[:：]\s*签字.*$", repl="", flags=0),
]


__all__ = ["RULES"]
