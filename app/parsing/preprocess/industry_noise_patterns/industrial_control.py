
from app.rag.preprocessing.cleaning import RegexRule

RULES: list[RegexRule] = [
    RegexRule(pattern=r"(?m)^\s*帖子列表\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*详细帖子内容\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*未知标题\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*共找到\s+\d+\s+个帖子\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*【主帖内容】\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*【回复\s+\d+\s*-\s*.*】\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*回复时间：.*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*暂无回复\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*点击文件名下载附件\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\([\d\.]+\s*(MB|KB|GB),\s*下载次数:\s*\d+\)\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*.*\.zip\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*您的浏览器不支持\s+video\s+或\s+audio\s+标签\s*$", repl="", flags=0),
    RegexRule(pattern=r"(?m)^\s*复制代码\s*$", repl="", flags=0),
]


__all__ = ["RULES"]
