"""
Multi-modal query router (deterministic).

Wave19-T063: Multi-modal query routing (text vs image vs table).

Design goals:
- Deterministic + auditable (no LLM calls).
- Low false-positives: prefer "table" when explicit SQL/aggregation intent exists.
- Safe defaults: fall back to "text" when unsure.
"""

from __future__ import annotations

import re

# Keep this aligned with chat_tag_service table intent detection, but avoid importing
# that module here to keep dependencies minimal and prevent accidental cycles.
_SQL_TABLE_INTENT_RE = re.compile(
    r"(?i)\b(select|where|group\s+by|order\s+by|limit|sum|avg|count|min|max|distinct|join)\b"
)
_TABLE_INTENT_RE = re.compile(
    r"(?i)统计|汇总|求和|平均|最大|最小|排名|Top\s*\d+|前\s*\d+|多少|几条|筛选|过滤|分组|占比"
)

_IMAGE_EXT_RE = re.compile(r"(?i)\.(png|jpg|jpeg|gif|webp|bmp)\b")
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_IMAGE_HINT_RE = re.compile(
    r"(?i)\b(image|picture|photo|diagram|figure|chart|screenshot|logo|plot|graph)\b"
    r"|图片|照片|截图|图像|示意图|流程图|图表|曲线图|柱状图|饼图|架构图|示例图|截图"
)


def classify_query_modality(query: str) -> tuple[str, list[str]]:
    """
    Return (modality, reason_codes).

    modality:
    - "table": query looks like SQL/aggregation over a tabular asset
    - "image": query asks for an image/figure/diagram/screenshot
    - "text": default (normal RAG)
    """
    q = str(query or "").strip()
    if not q:
        return "text", ["empty_query"]

    reasons: list[str] = []

    if _SQL_TABLE_INTENT_RE.search(q):
        reasons.append("sql_table_intent")
        return "table", reasons

    if _MARKDOWN_IMAGE_RE.search(q) or "data:image/" in q.lower() or "<img" in q.lower():
        reasons.append("image_inline")
        return "image", reasons

    if _IMAGE_EXT_RE.search(q):
        reasons.append("image_ext")
        return "image", reasons

    if _IMAGE_HINT_RE.search(q):
        reasons.append("image_hint")
        return "image", reasons

    if _TABLE_INTENT_RE.search(q):
        reasons.append("table_intent")
        return "table", reasons

    return "text", ["default"]


__all__ = ["classify_query_modality"]
