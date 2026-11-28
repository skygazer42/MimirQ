"""Deterministic query-shape decisions used by retrieval planning."""

import re

_AUTO_LIST_INTENT_RE = re.compile(r"(列举|有哪些|列表|对比|比较|分别|优缺点|差异|汇总|总结)", flags=re.IGNORECASE)


_AUTO_KEYWORD_HINT_RES = (
    re.compile(r"\b(?:traceback|exception|error)\b"),
    re.compile(r"stack\s*trace"),
    re.compile(r"http\s*\d{3}"),
    re.compile(r"0x[0-9a-f]{4,}"),
    re.compile(r"[a-z_][a-z0-9_]{2,}\("),
    re.compile(r"\.\w{1,5}\b"),
)


_RECALL_SCHEMA_HINT_RE = re.compile(r"(字段|column|columns|schema|表结构|ddl)", flags=re.IGNORECASE)


_RECALL_PROCEDURE_HINT_RE = re.compile(r"(如何|怎么|步骤|流程|how\s+to|steps?|procedure)", flags=re.IGNORECASE)


_RECALL_NUMERIC_HINT_RE = re.compile(r"(多少|总数|count|sum|avg|average|mean|max|min|最大|最小)", flags=re.IGNORECASE)


_RECALL_POLICY_HINT_RE = re.compile(r"(条例|规定|政策|条款|policy|regulation|compliance|law)", flags=re.IGNORECASE)


_RECALL_DEFINITION_HINT_RE = re.compile(r"(什么是|是什么|定义|define|meaning|what\s+is)", flags=re.IGNORECASE)


_QUERY_REWRITE_TRIGGER_SUBSTRINGS = (
    "它",
    "他",
    "她",
    "这个",
    "这段",
    "这部分",
    "这些",
    "那",
    "上述",
    "上面",
    "前面",
    "之前",
    "刚才",
    "上文",
    "下文",
    "这里",
    "那里",
    "继续",
    "同上",
    "同理",
)


def guess_recall_bucket(query: str) -> str:
    """
    Heuristic question-type classifier for recall routing.

    Returns one of:
    - schema | procedure | numeric | policy | definition | general
    """
    query = query.strip()
    if not query:
        return "general"

    # Order matters: prefer narrower buckets over broad "definition".
    if _RECALL_SCHEMA_HINT_RE.search(query):
        return "schema"
    if _RECALL_POLICY_HINT_RE.search(query):
        return "policy"
    if _RECALL_NUMERIC_HINT_RE.search(query):
        return "numeric"
    if _RECALL_PROCEDURE_HINT_RE.search(query):
        return "procedure"
    if _RECALL_DEFINITION_HINT_RE.search(query):
        return "definition"
    return "general"


def guess_retrieval_mode(query: str) -> str:
    """
    Heuristic retrieval mode router for `auto`.

    Returns one of: hybrid | keyword | mmr
    """
    query = query.strip()
    if not query:
        return "hybrid"

    if _AUTO_LIST_INTENT_RE.search(query):
        return "mmr"

    lower_query = query.lower()
    if any(hint.search(lower_query) for hint in _AUTO_KEYWORD_HINT_RES) or any(
        delimiter in lower_query for delimiter in ("/", "\\", "::")
    ):
        return "keyword"

    if len(query) <= 40 and not any("\u4e00" <= char <= "\u9fff" for char in query):
        if any(char.isascii() and not char.isspace() for char in query):
            return "keyword"

    return "hybrid"


def should_rewrite_query(question: str, *, short_len: int = 12) -> bool:
    """
    Heuristic guard for Query Rewrite (reduce unnecessary LLM calls).

    - Always rewrite very short follow-ups (likely coreference)
    - Otherwise, rewrite only when we detect coreference-like triggers
    """
    question = question.strip()
    if not question:
        return False
    if len(question) <= max(1, short_len):
        return True
    return any(trigger in question for trigger in _QUERY_REWRITE_TRIGGER_SUBSTRINGS)


__all__ = ["guess_recall_bucket", "guess_retrieval_mode", "should_rewrite_query"]
