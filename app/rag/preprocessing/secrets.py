"""
Secret/token redaction helpers for governance cleaning.

Goals:
- Catch common API keys/tokens/private keys with conservative patterns.
- Avoid network calls and heavy dependencies.
- Be code-fence agnostic (callers decide where to apply).
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Literal


SecretMode = Literal["mask", "token"]


@dataclass(frozen=True)
class SecretsRedactResult:
    text: str
    hits: dict[str, int]
    changed: bool


# NOTE: Patterns are intentionally conservative to reduce false positives.
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+([A-Za-z0-9\-_.]{12,})\b")
_GITHUB_TOKEN_RE = re.compile(r"\b(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})\b")
_AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_SLACK_TOKEN_RE = re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")

# Private key blocks (PEM). We redact the entire block.
_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    flags=re.MULTILINE,
)


def redact_secrets(text: str, *, enabled: bool, mode: SecretMode = "mask", mask: str = "[SECRET]") -> SecretsRedactResult:
    original = text or ""
    if not enabled or not original:
        return SecretsRedactResult(text=original, hits={}, changed=False)

    hits: dict[str, int] = {}
    token_maps: dict[str, dict[str, str]] = {}

    def make_replacer(
        kind: str,
        *,
        validator: Callable[[str], bool] | None = None,
        keep_prefix: str = "",
    ) -> Callable[[re.Match[str]], str]:
        token_map = token_maps.setdefault(kind, {})

        def repl(match: re.Match[str]) -> str:
            raw = match.group(0) or ""
            val = raw
            if keep_prefix and raw.lower().startswith(keep_prefix.lower()):
                val = raw[len(keep_prefix) :]
            if validator is not None and not validator(val):
                return raw

            hits[kind] = hits.get(kind, 0) + 1
            if mode == "mask":
                return f"{keep_prefix}{mask}" if keep_prefix else mask

            key = val
            existing = token_map.get(key)
            if existing:
                return f"{keep_prefix}{existing}" if keep_prefix else existing
            token = f"[SECRET_{kind.upper()}_{len(token_map) + 1}]"
            token_map[key] = token
            return f"{keep_prefix}{token}" if keep_prefix else token

        return repl

    current = original
    current = _PRIVATE_KEY_BLOCK_RE.sub(make_replacer("private_key"), current)
    current = _OPENAI_KEY_RE.sub(make_replacer("openai_key"), current)
    current = _GITHUB_TOKEN_RE.sub(make_replacer("github_token"), current)
    current = _SLACK_TOKEN_RE.sub(make_replacer("slack_token"), current)
    current = _AWS_ACCESS_KEY_RE.sub(make_replacer("aws_access_key"), current)

    # Bearer token: keep "Bearer " prefix for readability.
    current = _BEARER_TOKEN_RE.sub(make_replacer("bearer_token", keep_prefix="Bearer "), current)

    return SecretsRedactResult(text=current, hits=hits, changed=(current != original))


__all__ = [
    "SecretMode",
    "SecretsRedactResult",
    "redact_secrets",
]

