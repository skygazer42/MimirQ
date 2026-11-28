import hashlib
from collections.abc import Sequence
from typing import Any

from app.rag.industry_rules.appliers.query_rewrite import iter_query_aliases
from app.rag.industry_rules.loaders.yaml_loader import RulesetFormatError, load_ruleset

_SCHEMA = "mimirq.industry_rules_runtime.v1"


def normalize_ruleset_names(raw: str | Sequence[str] | None, *, max_items: int = 8) -> list[str]:
    if max_items < 0:
        raise ValueError("Ruleset name limit must not be negative")
    if raw is None or max_items == 0:
        return []
    if isinstance(raw, str):
        values = raw.replace(";", ",").split(",")
    elif isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        if any(not isinstance(item, str) for item in raw):
            raise TypeError("Ruleset names must be strings")
        values = raw
    else:
        raise TypeError("Ruleset names must be a string or a sequence of strings")

    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = value.strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= max_items:
            break
    return out


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _query_expansion_meta(original: str, *, enabled: bool, ruleset_names: list[str]) -> dict[str, Any]:
    query_hash = _hash_text(original)
    return {
        "schema": _SCHEMA,
        "enabled": enabled,
        "used": False,
        "rulesets_requested": ruleset_names,
        "rulesets_used": [],
        "alias_count": 0,
        "query_changed": False,
        "query_hash": query_hash,
        "expanded_query_hash": query_hash,
        "errors": [],
    }


def apply_industry_rules_query_expansion(
    query: str,
    *,
    enabled: bool,
    ruleset_names: str | Sequence[str] | None,
    max_aliases: int = 16,
    max_query_chars: int = 2000,
) -> tuple[str, dict[str, Any]]:
    """Bound alias growth; zero character budget is unlimited.

    The original query is retained even when it already exceeds a positive
    expansion budget. Only complete aliases that fit are added.
    """
    original = query.strip()
    if max_aliases < 0 or max_query_chars < 0:
        raise ValueError("Industry expansion budgets must not be negative")
    names = normalize_ruleset_names(ruleset_names)
    meta = _query_expansion_meta(original, enabled=enabled, ruleset_names=names)
    if not enabled or not original or not names or max_aliases == 0:
        return original, meta
    if max_query_chars > 0 and len(original) >= max_query_chars:
        return original, meta

    expanded = original
    aliases: set[str] = set()
    for name in names:
        try:
            ruleset = load_ruleset(name)
            before = expanded
            for alias in iter_query_aliases(before, ruleset.glossary):
                if alias in aliases or alias == original:
                    continue
                candidate = f"{expanded} {alias}"
                if max_query_chars > 0 and len(candidate) > max_query_chars:
                    continue
                aliases.add(alias)
                expanded = candidate
                if len(aliases) >= max_aliases:
                    break
            if expanded != before:
                meta["rulesets_used"].append(name)
        except (OSError, RulesetFormatError) as exc:
            meta["errors"].append({"ruleset": name, "error": str(exc)[:160]})
        if len(aliases) >= max_aliases:
            break

    meta["alias_count"] = len(aliases)
    meta["query_changed"] = expanded != original
    meta["used"] = meta["query_changed"]
    meta["expanded_query_hash"] = _hash_text(expanded)
    return expanded, meta


__all__ = ["apply_industry_rules_query_expansion", "normalize_ruleset_names"]
