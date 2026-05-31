"""
Fixed text splitter implementations.
Integrated from an upstream splitter implementation (vendored for stability).
"""

import re
from collections.abc import Callable, Collection, Set
from typing import Any, Literal, TypeVar

from app.rag.chunking.utils.splitters.text_splitter import RecursiveCharacterTextSplitter

TS = TypeVar("TS", bound="EnhanceRecursiveCharacterTextSplitter")


def _gpt2_token_count(text: str) -> int:
    """Count tokens using GPT-2 tokenizer (simple approximation)."""
    # Simple word-based approximation: ~4 chars per token on average
    return max(1, len(text) // 4)


class EnhanceRecursiveCharacterTextSplitter(RecursiveCharacterTextSplitter):
    """
    Enhanced RecursiveCharacterTextSplitter with encoder support.
    """

    @classmethod
    def from_encoder(
        cls: type[TS],
        embedding_model_instance: Any = None,
        allowed_special: Literal["all"] | Set[str] = set(),
        disallowed_special: Literal["all"] | Collection[str] = "all",
        token_counting_fn: Callable[[str], int] | None = None,
        **kwargs: Any,
    ) -> TS:
        """Create splitter with custom token counting function.

        Args:
            embedding_model_instance: Optional model instance for token counting
            allowed_special: Special tokens to allow
            disallowed_special: Special tokens to disallow
            token_counting_fn: Custom function to count tokens in text
            **kwargs: Additional arguments passed to the splitter
        """
        def _token_encoder(texts: list[str]) -> list[int]:
            if not texts:
                return []

            if token_counting_fn:
                return [token_counting_fn(text) for text in texts]

            if embedding_model_instance and hasattr(embedding_model_instance, "get_text_embedding_num_tokens"):
                fn = embedding_model_instance.get_text_embedding_num_tokens
                try:
                    return fn(texts=texts, allowed_special=allowed_special, disallowed_special=disallowed_special)
                except TypeError:
                    return fn(texts=texts)

            return [_gpt2_token_count(text) for text in texts]

        def _character_encoder(texts: list[str]) -> list[int]:
            if not texts:
                return []
            return [len(text) for text in texts]

        use_token_encoder = token_counting_fn is not None or embedding_model_instance is not None
        length_function = _token_encoder if use_token_encoder else _character_encoder
        return cls(length_function=length_function, **kwargs)


class FixedRecursiveCharacterTextSplitter(EnhanceRecursiveCharacterTextSplitter):
    """Fixed separator recursive character text splitter."""

    def __init__(self, fixed_separator: str = "\n\n", separators: list[str] | None = None, **kwargs: Any):
        """Create a new FixedRecursiveCharacterTextSplitter.

        Args:
            fixed_separator: Primary separator to split on first
            separators: List of fallback separators for recursive splitting
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._fixed_separator = fixed_separator
        self._separators = separators or ["\n\n", "\n", "。", ". ", " ", ""]

    def split_text(self, text: str) -> list[str]:
        """Split incoming text and return chunks."""
        if self._fixed_separator:
            chunks = text.split(self._fixed_separator)
        else:
            chunks = [text]

        final_chunks = []
        chunks_lengths = self._length_function(chunks)
        for chunk, chunk_length in zip(chunks, chunks_lengths, strict=False):
            if chunk_length > self._chunk_size:
                final_chunks.extend(self.recursive_split_text(chunk))
            else:
                final_chunks.append(chunk)

        return final_chunks

    def recursive_split_text(self, text: str) -> list[str]:
        """Recursively split text using configured separators."""
        final_chunks = []
        separator = self._separators[-1]
        new_separators = []

        for i, _s in enumerate(self._separators):
            if _s == "":
                separator = _s
                break
            if _s in text:
                separator = _s
                new_separators = self._separators[i + 1 :]
                break

        # Split text using the separator
        if separator:
            if separator == " ":
                splits = re.split(r" +", text)
            else:
                splits = text.split(separator)
                splits = [item + separator if i < len(splits) else item for i, item in enumerate(splits)]
        else:
            splits = list(text)

        if separator == "\n":
            splits = [s for s in splits if s != ""]
        else:
            splits = [s for s in splits if (s not in {"", "\n"})]

        _good_splits = []
        _good_splits_lengths = []
        _separator = separator if self._keep_separator else ""
        s_lens = self._length_function(splits)

        if separator != "":
            for s, s_len in zip(splits, s_lens, strict=False):
                if s_len < self._chunk_size:
                    _good_splits.append(s)
                    _good_splits_lengths.append(s_len)
                else:
                    if _good_splits:
                        merged_text = self._merge_splits(_good_splits, _separator, _good_splits_lengths)
                        final_chunks.extend(merged_text)
                        _good_splits = []
                        _good_splits_lengths = []
                    if not new_separators:
                        final_chunks.append(s)
                    else:
                        other_info = self._split_text(s, new_separators)
                        final_chunks.extend(other_info)

            if _good_splits:
                merged_text = self._merge_splits(_good_splits, _separator, _good_splits_lengths)
                final_chunks.extend(merged_text)
        else:
            # Character-by-character splitting with overlap
            current_part = ""
            current_length = 0
            overlap_part = ""
            overlap_part_length = 0
            for s, s_len in zip(splits, s_lens, strict=False):
                if current_length + s_len <= self._chunk_size - self._chunk_overlap:
                    current_part += s
                    current_length += s_len
                elif current_length + s_len <= self._chunk_size:
                    current_part += s
                    current_length += s_len
                    overlap_part += s
                    overlap_part_length += s_len
                else:
                    final_chunks.append(current_part)
                    current_part = overlap_part + s
                    current_length = s_len + overlap_part_length
                    overlap_part = ""
                    overlap_part_length = 0
            if current_part:
                final_chunks.append(current_part)

        return final_chunks
