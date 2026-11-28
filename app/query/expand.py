"""
Controlled, auditable query expansion utilities.

This module is intentionally deterministic and bounded:
- At most one rule application per expanded query (no combinatorial explosions).
- Stable de-duplication (ASCII case-insensitive).
- Expansion provenance is included with each generated variant.
"""

import re
from collections.abc import Iterator
from itertools import islice
from pathlib import Path
from typing import Any


def _unique_rule_values(key: str, raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = raw
    else:
        return []
    seen: set[str] = set()
    unique: list[str] = []
    for item in values:
        if item is None:
            continue
        value = str(item).strip()
        if not value or value == key:
            continue
        signature = value.casefold() if value.isascii() else value
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(value)
    return unique


def coerce_expansion_rules(raw: Any) -> dict[str, list[str]]:
    """
    Coerce a user/dataset-provided expansion dictionary into a normalized mapping.

    Expected shape:
      {
        "SLO": ["service level objective", "service-level objective"],
        "SSO": ["single sign-on", "single sign on"],
      }
    """
    if not isinstance(raw, dict):
        return {}

    out: dict[str, list[str]] = {}
    for k, v in raw.items():
        if k is None:
            continue
        key = str(k).strip()
        if not key:
            continue
        unique = _unique_rule_values(key, v)
        if unique:
            out[key] = unique
    return out


_WORD_EDGE = r"(?<![A-Za-z0-9_]){term}(?![A-Za-z0-9_])"


def _term_pattern(term: str) -> re.Pattern[str]:
    # For ASCII terms, apply case-insensitive match and avoid replacing substrings inside identifiers.
    return re.compile(_WORD_EDGE.format(term=re.escape(term)), flags=re.IGNORECASE)


def _contains(query: str, term: str) -> bool:
    if term.isascii():
        return _term_pattern(term).search(query) is not None
    return term in query


def _replace(query: str, term: str, replacement: str) -> str:
    if term.isascii():
        return _term_pattern(term).sub(lambda _: replacement, query)
    return query.replace(term, replacement)


def _bounded_query(text: str, max_query_chars: int) -> str:
    text = text.strip()
    if max_query_chars and len(text) > max_query_chars:
        return text[:max_query_chars] + "..."
    return text


def _append_rule_expansions(
    *,
    expansions: list[dict[str, Any]],
    seen: set[str],
    base: str,
    source: str,
    targets: list[str],
    max_expansions_total: int,
    max_expansions_per_rule: int,
    max_query_chars: int,
) -> None:
    per_rule = 0
    for target in targets:
        if len(expansions) >= max_expansions_total or per_rule >= max_expansions_per_rule:
            break
        expanded = _bounded_query(_replace(base, source, target), max_query_chars)
        if not expanded or expanded == base:
            continue
        signature = expanded.casefold() if expanded.isascii() else expanded
        if signature in seen:
            continue
        seen.add(signature)
        expansions.append(
            {
                "expanded_text": expanded,
                "source_rule_id": f"dict:{source}",
                "weight": 1.0,
                "src": source,
                "tgt": target,
            }
        )
        per_rule += 1


def generate_dictionary_expansions(
    *,
    query: str,
    rules: dict[str, list[str]] | None,
    max_expansions_total: int = 5,
    max_expansions_per_rule: int = 2,
    max_query_chars: int = 400,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Generate query variants by applying deterministic dictionary rules.

    Returns:
      - expansions: list[dict] each containing {expanded_text, source_rule_id, weight, ...}
      - meta: small dict for traces/metrics
    """
    base = query.strip()
    if not base:
        return [], {"enabled": False, "used": False, "reason": "empty_query"}

    max_expansions_total = max(0, int(max_expansions_total or 0))
    max_expansions_per_rule = max(0, int(max_expansions_per_rule or 0))
    if max_expansions_total <= 0 or max_expansions_per_rule <= 0:
        return [], {"enabled": False, "used": False, "reason": "disabled"}

    rules_in = coerce_expansion_rules(rules)
    if not rules_in:
        return [], {"enabled": False, "used": False, "reason": "no_rules"}

    expansions: list[dict[str, Any]] = []
    seen: set[str] = set()

    for key, targets in rules_in.items():
        if len(expansions) >= max_expansions_total:
            break
        if not _contains(base, key):
            continue
        _append_rule_expansions(
            expansions=expansions,
            seen=seen,
            base=base,
            source=key,
            targets=targets,
            max_expansions_total=max_expansions_total,
            max_expansions_per_rule=max_expansions_per_rule,
            max_query_chars=max_query_chars,
        )

    return expansions, {
        "enabled": True,
        "used": bool(expansions),
        "generated": len(expansions),
        "rules_total": len(rules_in),
        "max_expansions_total": max_expansions_total,
        "max_expansions_per_rule": max_expansions_per_rule,
        "base_query_chars": len(base),
    }


def _dictionary_heading(line: str, stripped: str) -> str | None:
    if line.startswith((" ", "\t")) or not stripped.endswith(":"):
        return None
    return stripped[:-1].strip().strip('"').strip("'")


def _dictionary_list_value(stripped: str) -> str | None:
    if not stripped.startswith("-"):
        return None
    value = stripped[1:].strip()
    if not value:
        return None
    quoted = (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'"))
    if quoted and len(value) >= 2:
        return value[1:-1]
    return value


def load_base_dictionary_rules() -> dict[str, list[str]]:
    """
    Load the bundled dictionary rules from `app/query/dictionaries/base.yaml`.

    We intentionally use a tiny YAML subset parser to avoid adding a YAML dependency.
    Supported subset:
      KEY:
        - value
        - value2
    """
    path = Path(__file__).resolve().parent / "dictionaries" / "base.yaml"
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    parsed: dict[str, list[str]] = {}
    current_key: str | None = None
    for ln in raw.splitlines():
        line = ln.rstrip("\r\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        heading = _dictionary_heading(line, stripped)
        if heading is not None:
            current_key = heading if heading else None
            if current_key and current_key not in parsed:
                parsed[current_key] = []
            continue
        value = _dictionary_list_value(stripped)
        if value is not None and current_key:
            parsed.setdefault(current_key, []).append(value)

    return coerce_expansion_rules(parsed)


def coerce_query_aliases(raw: Any) -> dict[str, list[str]]:
    """
    Coerce a dataset/request-provided alias dictionary into a normalized mapping.

    Expected shape:
      {
        "单点登录": ["SSO", "Single Sign-On"],
        "LLM": ["large language model"],
      }
    """
    if not isinstance(raw, dict):
        return {}

    out: dict[str, list[str]] = {}
    for k, v in raw.items():
        key = k.strip()
        if not key:
            continue
        unique = _unique_rule_values(key, v)
        if unique:
            out[key] = unique
    return out


def _query_contains_alias(base: str, base_fold: str, source: str) -> bool:
    if source.isascii():
        return source.casefold() in base_fold
    return source in base


def _replace_alias(base: str, source: str, target: str) -> str:
    if source.isascii():
        return re.sub(re.escape(source), lambda _: target, base, flags=re.IGNORECASE)
    return base.replace(source, target)


def _symmetric_alias_pairs(rules: dict[str, list[str]]) -> Iterator[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    for key, aliases in rules.items():
        key_signature = key.casefold() if key.isascii() else key
        for alias in aliases:
            alias_signature = alias.casefold() if alias.isascii() else alias
            for pair, signature in (
                ((key, alias), (key_signature, alias_signature)),
                ((alias, key), (alias_signature, key_signature)),
            ):
                if signature not in seen:
                    seen.add(signature)
                    yield pair


def generate_alias_queries(
    *,
    query: str,
    aliases: dict[str, list[str]] | None,
    max_queries: int = 5,
    max_rules: int = 200,
    max_query_chars: int = 400,
) -> tuple[list[str], dict[str, Any]]:
    """
    Generate query variants by applying dataset-scoped alias rules.

    Design notes:
    - One rule application per generated query (no combinatorial explosions).
    - Case-insensitive matching for ASCII rules, exact for non-ASCII.
    - Returns both the variants and a small meta payload for traces/metrics.
    """
    base = query.strip()
    if not base:
        return [], {"enabled": False, "used": False, "reason": "empty_query"}

    max_queries = max(0, int(max_queries or 0))
    if max_queries <= 0:
        return [], {"enabled": False, "used": False, "reason": "max_queries_le_0"}

    rules_in = coerce_query_aliases(aliases)
    if not rules_in:
        return [], {"enabled": False, "used": False, "reason": "no_aliases"}

    base_fold = base.casefold()
    variants: list[str] = []
    seen: set[str] = set()
    applied: list[dict[str, str]] = []
    pairs = list(islice(_symmetric_alias_pairs(rules_in), max(0, max_rules)))
    for src, tgt in pairs:
        if len(variants) >= max_queries:
            break
        if not _query_contains_alias(base, base_fold, src):
            continue
        v = _bounded_query(_replace_alias(base, src, tgt), max_query_chars)
        if not v or v == base:
            continue
        sig = v.casefold() if v.isascii() else v
        if sig in seen:
            continue
        seen.add(sig)
        variants.append(v)
        applied.append({"src": src, "tgt": tgt})

    return variants, {
        "enabled": True,
        "used": bool(variants),
        "base_query_chars": len(base),
        "max_queries": max_queries,
        "rules_total": sum(len(v) for v in rules_in.values()),
        "rules_considered": len(pairs),
        "generated": len(variants),
        "applied": applied[:8],
        "queries": variants[:8],
    }


_QUERY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}")


_DECOMPOSE_STRONG_SPLIT_RE = re.compile(r"[?？。.!！;；\n]+")


_DECOMPOSE_CONJ_SPLIT_EN_TOKENS = frozenset({"and", "or", "also", "plus", "then"})


_DECOMPOSE_CONJ_SPLIT_CN_RE = re.compile(r"(?:以及|并且|同时|另外|此外|还有|然后)")


_DECOMPOSE_LEADING_FILLER_RE = re.compile(
    r"^(?:and|or|also|then)\s+",
    flags=re.IGNORECASE,
)


_DECOMPOSE_TRAILING_PUNCT = " \t\r\n,，;；:：.!?。！？"


def _append_word_fragment(out: list[str], buf: list[str]) -> None:
    if buf:
        out.append(" ".join(buf))
        buf.clear()


def _is_as_well_as(tokens: list[str], index: int) -> bool:
    return (
        index + 2 < len(tokens)
        and tokens[index].casefold() == "as"
        and tokens[index + 1].casefold() == "well"
        and tokens[index + 2].casefold() == "as"
    )


def _split_on_en_conjunctions(text: str) -> list[str]:
    """
    Split text on common English conjunctions without regex.
    """
    tokens = (text).split()
    if len(tokens) < 3:
        return [text] if text else []

    out: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        low = t.casefold()

        # "as well as" is treated as a conjunction splitter.
        if low == "as" and _is_as_well_as(tokens, i):
            _append_word_fragment(out, buf)
            i += 3
            continue

        if low in _DECOMPOSE_CONJ_SPLIT_EN_TOKENS:
            _append_word_fragment(out, buf)
            i += 1
            continue

        buf.append(t)
        i += 1

    _append_word_fragment(out, buf)
    return out or ([text] if text else [])


def _clean_decomposed_fragment(text: str) -> str:
    cleaned = (text).strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^[-*•]\s+", "", cleaned)
    cleaned = re.sub(r"^\d+\s*[.)]\s+", "", cleaned)
    cleaned = cleaned.strip().strip('"').strip("'").strip()
    cleaned = _DECOMPOSE_LEADING_FILLER_RE.sub("", cleaned).strip()
    cleaned = cleaned.strip(_DECOMPOSE_TRAILING_PUNCT).strip()
    return " ".join(cleaned.split())


def _decomposition_fragments(raw: str) -> list[str]:
    fragments: list[str] = []
    for chunk in [c.strip() for c in _DECOMPOSE_STRONG_SPLIT_RE.split(raw) if c.strip()]:
        for frag_en in _split_on_en_conjunctions(chunk):
            for frag in _DECOMPOSE_CONJ_SPLIT_CN_RE.split(frag_en):
                cleaned = _clean_decomposed_fragment(frag)
                if cleaned:
                    fragments.append(cleaned)
    return fragments


def _is_useful_decomposed_fragment(fragment: str) -> bool:
    tokens = _QUERY_TOKEN_RE.findall(fragment)
    return not (len(fragment) < 8 and len(tokens) < 2)


def _bounded_unique_fragments(fragments: list[str], *, max_items: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for frag in fragments:
        if not _is_useful_decomposed_fragment(frag):
            continue
        key = frag.casefold() if frag.isascii() else frag
        if key in seen:
            continue
        seen.add(key)
        if len(frag) > 500:
            frag = frag[:500] + "..."
        out.append(frag)
        if len(out) >= max_items:
            break
    return out


def heuristic_decompose_query(query: str, *, max_subquestions: int = 3) -> list[str]:
    """
    Deterministic query decomposition helper (no LLM).

    Splits a multi-part question into <= N sub-questions using punctuation and
    common conjunctions. Designed as a safe fallback when LLM decomposition is
    unavailable.
    """

    max_subquestions = max(0, int(max_subquestions or 0))
    raw = (query).strip()
    if not raw or max_subquestions <= 0:
        return []

    out = _bounded_unique_fragments(_decomposition_fragments(raw), max_items=max_subquestions)
    if not out:
        return []

    # Avoid returning a single "decomposed" fragment that is identical to input.
    if len(out) == 1 and out[0] == " ".join(raw.split()):
        return []

    return out
