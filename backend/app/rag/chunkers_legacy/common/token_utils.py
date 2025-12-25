"""
Token utilities for ragflow.
Integrated from third_party/ragflow/common/token_utils.py
"""
import os
from typing import Any

try:
    import tiktoken
    _encoder = tiktoken.get_encoding("cl100k_base")
except ImportError:
    _encoder = None


def num_tokens_from_string(string: str) -> int:
    """Returns the number of tokens in a text string."""
    if _encoder is None:
        return max(1, len(string) // 4)
    try:
        code_list = _encoder.encode(string)
        return len(code_list)
    except Exception:
        return 0


def total_token_count_from_response(resp: Any) -> int:
    """Extract token count from LLM response in various formats."""
    if resp is None:
        return 0

    if hasattr(resp, "usage") and hasattr(resp.usage, "total_tokens"):
        try:
            return resp.usage.total_tokens
        except Exception:
            pass

    if hasattr(resp, "usage_metadata") and hasattr(resp.usage_metadata, "total_tokens"):
        try:
            return resp.usage_metadata.total_tokens
        except Exception:
            pass

    if isinstance(resp, dict) and 'usage' in resp and 'total_tokens' in resp['usage']:
        try:
            return resp["usage"]["total_tokens"]
        except Exception:
            pass

    if isinstance(resp, dict) and 'usage' in resp:
        usage = resp['usage']
        if 'input_tokens' in usage and 'output_tokens' in usage:
            try:
                return usage["input_tokens"] + usage["output_tokens"]
            except Exception:
                pass

    if isinstance(resp, dict) and 'meta' in resp and 'tokens' in resp['meta']:
        tokens = resp['meta']['tokens']
        if 'input_tokens' in tokens and 'output_tokens' in tokens:
            try:
                return tokens["input_tokens"] + tokens["output_tokens"]
            except Exception:
                pass

    return 0


def truncate(string: str, max_len: int) -> str:
    """Returns truncated text if the length exceeds max_len tokens."""
    if _encoder is None:
        char_limit = max_len * 4
        return string[:char_limit] if len(string) > char_limit else string
    return _encoder.decode(_encoder.encode(string)[:max_len])
