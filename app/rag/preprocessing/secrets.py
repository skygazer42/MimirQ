"""
Secret/token redaction helpers for governance cleaning.

Goals:
- Catch common API keys/tokens/private keys with conservative patterns.
- Avoid network calls and heavy dependencies.
- Be code-fence agnostic (callers decide where to apply).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

SecretMode = Literal["mask", "token"]


@dataclass(frozen=True)
class SecretsRedactResult:
    text: str
    hits: dict[str, int]
    changed: bool


@dataclass(frozen=True)
class SecretMatch:
    kind: str
    start: int
    end: int
    text: str


# NOTE: Patterns are intentionally conservative to reduce false positives.
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+([A-Z0-9\-_.]{12,})\b")
_GITHUB_TOKEN_RE = re.compile(r"\b(?:ghp_[A-Za-z0-9]{30,}|github_pat_\w{20,})\b")
_AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_SLACK_TOKEN_RE = re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")

# Private key blocks (PEM). We redact the entire block.
_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    flags=re.MULTILINE,
)
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("private_key", _PRIVATE_KEY_BLOCK_RE, ""),
    ("openai_key", _OPENAI_KEY_RE, ""),
    ("github_token", _GITHUB_TOKEN_RE, ""),
    ("slack_token", _SLACK_TOKEN_RE, ""),
    ("aws_access_key", _AWS_ACCESS_KEY_RE, ""),
    ("bearer_token", _BEARER_TOKEN_RE, "Bearer "),
]


def redact_secrets(
    text: str, *, enabled: bool, mode: SecretMode = "mask", mask: str = "[SECRET]"
) -> SecretsRedactResult:
    original = text
    if not enabled or not original:
        return SecretsRedactResult(text=original, hits={}, changed=False)

    hits: dict[str, int] = {}
    token_maps: dict[str, dict[str, str]] = {}

    def make_replacer(kind: str, *, keep_prefix: str) -> Callable[[re.Match[str]], str]:
        token_map = token_maps.setdefault(kind, {})

        def repl(match: re.Match[str]) -> str:
            raw = match.group(0)
            val = raw
            if keep_prefix and raw.lower().startswith(keep_prefix.lower()):
                val = raw[len(keep_prefix) :]
            hits[kind] = hits.get(kind, 0) + 1
            if mode == "mask":
                return f"{keep_prefix}{mask}" if keep_prefix else mask

            existing = token_map.get(val)
            if existing:
                return f"{keep_prefix}{existing}" if keep_prefix else existing
            token = f"[SECRET_{kind.upper()}_{len(token_map) + 1}]"
            token_map[val] = token
            return f"{keep_prefix}{token}" if keep_prefix else token

        return repl

    current = original
    for kind, pattern, keep_prefix in _SECRET_PATTERNS:
        current = pattern.sub(make_replacer(kind, keep_prefix=keep_prefix), current)

    return SecretsRedactResult(text=current, hits=hits, changed=(current != original))


def find_secret_matches(text: str, *, max_matches: int = 50) -> list[SecretMatch]:
    """
    Find secret/token candidates in text (best-effort).

    Intended for review-time displays (precheck / governance debug). Results are
    conservative but still require human verification.
    """
    if not text:
        return []

    max_matches = max(0, min(int(max_matches or 0), 200))
    if max_matches <= 0:
        return []

    taken: list[tuple[int, int]] = []
    out: list[SecretMatch] = []

    for kind, pat, _keep_prefix in _SECRET_PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(0)
            start, end = m.start(), m.end()
            if any(start < taken_end and end > taken_start for taken_start, taken_end in taken):
                continue
            out.append(SecretMatch(kind=kind, start=start, end=end, text=raw))
            taken.append((start, end))
            if len(out) >= max_matches:
                break
        if len(out) >= max_matches:
            break

    out.sort(key=lambda x: (x.start, x.end))
    return out


__all__ = [
    "SecretMode",
    "SecretsRedactResult",
    "redact_secrets",
    "SecretMatch",
    "find_secret_matches",
]
