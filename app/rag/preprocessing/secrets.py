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
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", _PRIVATE_KEY_BLOCK_RE),
    ("openai_key", _OPENAI_KEY_RE),
    ("github_token", _GITHUB_TOKEN_RE),
    ("slack_token", _SLACK_TOKEN_RE),
    ("aws_access_key", _AWS_ACCESS_KEY_RE),
    ("bearer_token", _BEARER_TOKEN_RE),
]


def redact_secrets(
    text: str, *, enabled: bool, mode: SecretMode = "mask", mask: str = "[SECRET]"
) -> SecretsRedactResult:
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


def _overlaps_taken(a0: int, a1: int, taken: list[tuple[int, int]]) -> bool:
    for b0, b1 in taken:
        if a0 < b1 and a1 > b0:
            return True
    return False


def find_secret_matches(text: str, *, max_matches: int = 50) -> list[SecretMatch]:
    """
    Find secret/token candidates in text (best-effort).

    Intended for review-time displays (precheck / governance debug). Results are
    conservative but still require human verification.
    """
    s = text or ""
    if not s:
        return []

    max_matches = max(0, min(int(max_matches or 0), 200))
    if max_matches <= 0:
        return []

    taken: list[tuple[int, int]] = []
    out: list[SecretMatch] = []

    for kind, pat in _SECRET_PATTERNS:
        for m in pat.finditer(s):
            raw = m.group(0) or ""
            if not raw:
                continue
            start, end = int(m.start()), int(m.end())
            if start < 0 or end <= start:
                continue
            if _overlaps_taken(start, end, taken):
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
