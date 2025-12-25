"""
Keyword extraction helpers used by governance/reranking.

Canonical home for Jieba keyword extraction (previously under `app.rag.nlp.keyword`).
"""

from app.governance.keyword.jieba.stopwords import STOPWORDS
from app.governance.keyword.jieba.jieba_handler import JiebaKeywordTableHandler

__all__ = ["STOPWORDS", "JiebaKeywordTableHandler"]

