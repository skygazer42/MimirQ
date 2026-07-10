
from app.rag.preprocessing.cleaning import RegexRule

RULES: list[RegexRule] = [
    RegexRule(pattern=r"(?m)^\s*本报告由.*制作.*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*风险提示[:：]?.*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*单位[:：]\s*(元|万元|亿元)\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*免责声明[:：]?.*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*请务必阅读正文之后的免责声明部分\s*$", repl="", flags=0),
]


__all__ = ["RULES"]
