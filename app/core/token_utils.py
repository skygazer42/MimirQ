"""
Token utility module.

Provides token counting and truncation functionality based on tiktoken.
Supports cl100k_base encoding (GPT-4, GPT-3.5-turbo, etc.).
"""
from typing import Any

_encoder = None


def _get_encoder():
    """Lazy load the tiktoken encoder."""
    global _encoder
    if _encoder is None:
        import tiktoken

        try:
            _encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:  # noqa: BLE001
            # tiktoken may attempt to download encoding assets on first use in some
            # environments. In CI/offline contexts this can fail (network/proxy).
            # Fail open to the heuristic fallback instead of crashing the request.
            _encoder = False
    return _encoder


def num_tokens_from_string(string: str) -> int:
    """Returns the number of tokens in a text string.

    Uses cl100k_base encoding (GPT-4, GPT-3.5-turbo).
    Falls back to approximate 4 chars per token if tiktoken unavailable.

    Args:
        string: Text to count tokens in

    Returns:
        Number of tokens, or 0 if encoding fails
    """
    encoder = _get_encoder()
    if encoder is False:
        # Fallback: approximate 4 chars per token
        return max(1, len(string) // 4)
    try:
        return len(encoder.encode(string))
    except (TypeError, ValueError):
        return max(1, len(string) // 4)


def total_token_count_from_response(resp: Any) -> int:
    """Extract token count from LLM response in various formats.

    Handles different response structures from various LLM providers:
    - OpenAI: resp.usage.total_tokens
    - Google: resp.usage_metadata.total_tokens
    - Dict: resp['usage']['total_tokens']
    - Cohere: resp['meta']['tokens']['input_tokens'] + output_tokens

    Args:
        resp: Response object from LLM call

    Returns:
        Total token count, or 0 if cannot be determined
    """
    if resp is None:
        return 0

    # OpenAI-style response
    usage = getattr(resp, "usage", None)
    total_tokens = getattr(usage, "total_tokens", None)
    if isinstance(total_tokens, int) and not isinstance(total_tokens, bool):
        return total_tokens

    # Google-style response
    usage_metadata = getattr(resp, "usage_metadata", None)
    total_tokens = getattr(usage_metadata, "total_tokens", None)
    if isinstance(total_tokens, int) and not isinstance(total_tokens, bool):
        return total_tokens

    # Dict with usage.total_tokens
    if isinstance(resp, dict):
        usage = resp.get("usage", {})
        if isinstance(usage, dict):
            total_tokens = usage.get("total_tokens")
            if isinstance(total_tokens, int) and not isinstance(total_tokens, bool):
                return total_tokens

            # Dict with usage.input_tokens + output_tokens
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if (
                isinstance(input_tokens, int)
                and not isinstance(input_tokens, bool)
                and isinstance(output_tokens, int)
                and not isinstance(output_tokens, bool)
            ):
                return input_tokens + output_tokens

    # Cohere-style response
    if isinstance(resp, dict):
        meta = resp.get("meta", {})
        if isinstance(meta, dict):
            tokens = meta.get("tokens", {})
            if isinstance(tokens, dict):
                input_tokens = tokens.get("input_tokens")
                output_tokens = tokens.get("output_tokens")
                if (
                    isinstance(input_tokens, int)
                    and not isinstance(input_tokens, bool)
                    and isinstance(output_tokens, int)
                    and not isinstance(output_tokens, bool)
                ):
                    return input_tokens + output_tokens

    return 0


def truncate(string: str, max_len: int) -> str:
    """Truncate text to maximum token length.

    Uses cl100k_base encoding. Falls back to character approximation
    if tiktoken unavailable (max_len * 4 chars).

    Args:
        string: Text to truncate
        max_len: Maximum number of tokens

    Returns:
        Truncated text
    """
    encoder = _get_encoder()
    if encoder is False:
        # Fallback: approximate by characters (4 chars per token)
        char_limit = max_len * 4
        return string[:char_limit] if len(string) > char_limit else string

    try:
        return encoder.decode(encoder.encode(string)[:max_len])
    except (TypeError, ValueError):
        return string


def estimate_tokens(text: str) -> int:
    """
    Fast token estimation (heuristic).

    Notes:
    - Keep legacy behavior for ASCII-only text (~4 chars/token).
    - For CJK-heavy text, treat CJK-ish characters as ~1 char/token to avoid
      severe under-estimation (important for token-based guards and previews).
    """
    raw = text or ""
    if not raw:
        return 0

    if raw.isascii():
        return max(1, len(raw) // 4)

    cjk = 0
    for ch in raw:
        o = ord(ch)
        if (
            0x4E00 <= o <= 0x9FFF  # CJK Unified Ideographs
            or 0x3040 <= o <= 0x30FF  # Hiragana + Katakana
            or 0xAC00 <= o <= 0xD7AF  # Hangul Syllables
        ):
            cjk += 1

    non_cjk = len(raw) - cjk
    return max(1, cjk + (non_cjk // 4))


__all__ = [
    "num_tokens_from_string",
    "total_token_count_from_response",
    "truncate",
    "estimate_tokens",
]
