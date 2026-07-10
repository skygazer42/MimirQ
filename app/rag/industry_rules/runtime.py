
import hashlib
from collections.abc import Sequence
from typing import Any

from app.rag.industry_rules.appliers.query_rewrite import expand_query_terms
from app.rag.industry_rules.loaders.yaml_loader import load_ruleset

_SCHEMA = "mimirq.industry_rules_runtime.v1"


def normalize_ruleset_names(raw: Any, *, max_items: int = 8) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = [p.strip() for p in raw.replace(";", ",").split(",")]
    elif isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        values = [str(item or "").strip() for item in raw]
    else:
        values = [str(raw or "").strip()]

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
        if len(out) >= max(1, int(max_items or 1)):
            break
    return out


def _hash_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def apply_industry_rules_query_expansion(
    query: str,
    *,
    enabled: bool,
    ruleset_names: Any,
    max_aliases: int = 16,
    max_query_chars: int = 2000,
) -> tuple[str, dict[str, Any]]:
    original = str(query or "").strip()
    max_aliases_i = max(0, int(max_aliases or 0))
    max_query_chars_i = max(64, int(max_query_chars or 2000))
    names = normalize_ruleset_names(ruleset_names)
    meta: dict[str, Any] = {
        "schema": _SCHEMA,
        "enabled": bool(enabled),
        "used": False,
        "rulesets_requested": names,
        "rulesets_used": [],
        "alias_count": 0,
        "query_changed": False,
        "query_hash": _hash_text(original),
        "expanded_query_hash": _hash_text(original),
        "errors": [],
    }
    if not bool(enabled) or not original or not names or max_aliases_i <= 0:
        return original, meta

    expanded = original
    aliases: list[str] = []
    for name in names:
        try:
            ruleset = load_ruleset(name)
            before = expanded
            after = expand_query_terms(expanded, ruleset.glossary)
            if after == before:
                continue
            for term, values in (ruleset.glossary or {}).items():
                token = str(term or "").strip()
                if not token or token not in before:
                    continue
                for value in values or []:
                    alias = str(value or "").strip()
                    if alias and alias not in aliases:
                        aliases.append(alias)
            expanded = after
            meta["rulesets_used"].append(name)
        except Exception as exc:  # noqa: BLE001
            meta["errors"].append({"ruleset": name, "error": str(exc)[:160]})
        if len(aliases) >= max_aliases_i:
            break

    if aliases:
        capped_aliases = aliases[:max_aliases_i]
        expanded = " ".join([original, *capped_aliases]).strip()
    if len(expanded) > max_query_chars_i:
        expanded = expanded[:max_query_chars_i].rstrip()

    meta["alias_count"] = max(0, len([a for a in aliases[:max_aliases_i] if a]))
    meta["query_changed"] = expanded != original
    meta["used"] = bool(meta["query_changed"])
    meta["expanded_query_hash"] = _hash_text(expanded)
    return expanded, meta


__all__ = ["apply_industry_rules_query_expansion", "normalize_ruleset_names"]
