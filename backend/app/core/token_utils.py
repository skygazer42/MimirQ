"""
Token 工具模块

提供基于 tiktoken 的 token 计数和截断功能。
支持 cl100k_base 编码（GPT-4、GPT-3.5-turbo 等）。
"""
from typing import Any
_encoder = None


def _get_encoder():
    """Lazy load the tiktoken encoder."""
    global _encoder
    if _encoder is None:
        try:
            import tiktoken
            _encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            _encoder = False  # Mark as unavailable
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
    except Exception:
        return 0


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
    if hasattr(resp, "usage") and hasattr(resp.usage, "total_tokens"):
        try:
            return resp.usage.total_tokens
        except Exception:
            pass

    # Google-style response
    if hasattr(resp, "usage_metadata") and hasattr(resp.usage_metadata, "total_tokens"):
        try:
            return resp.usage_metadata.total_tokens
        except Exception:
            pass

    # Dict with usage.total_tokens
    if isinstance(resp, dict):
        usage = resp.get("usage", {})
        if "total_tokens" in usage:
            try:
                return usage["total_tokens"]
            except Exception:
                pass

        # Dict with usage.input_tokens + output_tokens
        if "input_tokens" in usage and "output_tokens" in usage:
            try:
                return usage["input_tokens"] + usage["output_tokens"]
            except Exception:
                pass

    # Cohere-style response
    if isinstance(resp, dict) and "meta" in resp:
        tokens = resp["meta"].get("tokens", {})
        if "input_tokens" in tokens and "output_tokens" in tokens:
            try:
                return tokens["input_tokens"] + tokens["output_tokens"]
            except Exception:
                pass

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
    except Exception:
        return string


def estimate_tokens(text: str) -> int:
    """Fast token estimation (char count / 4).

    Useful for quick estimates without tiktoken overhead.
    For accurate counts, use num_tokens_from_string().

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count
    """
    return max(1, len(text) // 4)


__all__ = [
    "num_tokens_from_string",
    "total_token_count_from_response",
    "truncate",
    "estimate_tokens",
]
