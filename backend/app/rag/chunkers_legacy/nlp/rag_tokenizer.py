"""
RAG tokenizer wrapper.
Integrated from third_party/ragflow/nlp/rag_tokenizer.py
"""
from app.ai.deepdoc.src.model.rag_tokenizer import RagTokenizer as DeepDocRagTokenizer


class RagTokenizer(DeepDocRagTokenizer):
    """RAG tokenizer with optional infinity engine support."""

    def __init__(self, use_infinity: bool = False):
        super().__init__()
        self._use_infinity = use_infinity

    def tokenize(self, line: str) -> str:
        if self._use_infinity:
            return line
        else:
            return super().tokenize(line)

    def fine_grained_tokenize(self, tks: str) -> str:
        if self._use_infinity:
            return tks
        else:
            return super().fine_grained_tokenize(tks)


# Default tokenizer instance
tokenizer = RagTokenizer()
tokenize = tokenizer.tokenize
fine_grained_tokenize = tokenizer.fine_grained_tokenize
tag = tokenizer.tag
freq = tokenizer.freq
tradi2simp = tokenizer._tradi2simp
strQ2B = tokenizer._strQ2B
