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


def _select_separator(text: str, separators: list[str]) -> tuple[str, list[str]]:
    separator = separators[-1]
    remaining: list[str] = []
    for index, candidate in enumerate(separators):
        if candidate == "":
            return candidate, remaining
        if candidate in text:
            return candidate, separators[index + 1 :]
    return separator, remaining


def _split_on_separator(text: str, separator: str) -> list[str]:
    if not separator:
        return list(text)
    if separator == " ":
        return re.split(r" +", text)
    parts = text.split(separator)
    return [item + separator if index < len(parts) else item for index, item in enumerate(parts)]


def _filter_separator_splits(splits: list[str], *, separator: str) -> list[str]:
    if separator == "\n":
        return [item for item in splits if item != ""]
    return [item for item in splits if item not in {"", "\n"}]


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

    def _split_with_separator(
        self,
        splits: list[str],
        split_lengths: list[int],
        *,
        separator: str,
        remaining_separators: list[str],
    ) -> list[str]:
        final_chunks: list[str] = []
        good_splits: list[str] = []
        good_lengths: list[int] = []
        merge_separator = separator if self._keep_separator else ""
        for split, split_length in zip(splits, split_lengths, strict=False):
            if split_length < self._chunk_size:
                good_splits.append(split)
                good_lengths.append(split_length)
                continue
            if good_splits:
                final_chunks.extend(self._merge_splits(good_splits, merge_separator, good_lengths))
                good_splits = []
                good_lengths = []
            if remaining_separators:
                final_chunks.extend(self._split_text(split, remaining_separators))
            else:
                final_chunks.append(split)
        if good_splits:
            final_chunks.extend(self._merge_splits(good_splits, merge_separator, good_lengths))
        return final_chunks

    def _split_characters(self, splits: list[str], split_lengths: list[int]) -> list[str]:
        final_chunks: list[str] = []
        current_part = ""
        current_length = 0
        overlap_part = ""
        overlap_length = 0
        for split, split_length in zip(splits, split_lengths, strict=False):
            if current_length + split_length <= self._chunk_size - self._chunk_overlap:
                current_part += split
                current_length += split_length
                continue
            if current_length + split_length <= self._chunk_size:
                current_part += split
                current_length += split_length
                overlap_part += split
                overlap_length += split_length
                continue
            final_chunks.append(current_part)
            current_part = overlap_part + split
            current_length = split_length + overlap_length
            overlap_part = ""
            overlap_length = 0
        if current_part:
            final_chunks.append(current_part)
        return final_chunks

    def recursive_split_text(self, text: str) -> list[str]:
        """Recursively split text using configured separators."""
        separator, remaining = _select_separator(text, self._separators)
        splits = _filter_separator_splits(
            _split_on_separator(text, separator),
            separator=separator,
        )
        split_lengths = self._length_function(splits)
        if not separator:
            return self._split_characters(splits, split_lengths)
        return self._split_with_separator(
            splits,
            split_lengths,
            separator=separator,
            remaining_separators=remaining,
        )
