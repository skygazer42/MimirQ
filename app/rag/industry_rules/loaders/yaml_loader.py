from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from app.rag.industry_rules.schema import IndustryRuleset
_GLOSSARY_FILENAME = "glossary.yaml"


def _ruleset_root() -> Path:
    return Path(__file__).resolve().parents[1] / "rulesets"


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: Any) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _normalize_glossary(glossary: Any) -> dict[str, list[str]]:
    if not isinstance(glossary, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for key, value in glossary.items():
        term = str(key or "").strip()
        if not term:
            continue
        aliases: list[str] = []
        if isinstance(value, (list, tuple, set)):
            aliases = [str(item or "").strip() for item in value if str(item or "").strip()]
        elif value is not None:
            alias = str(value or "").strip()
            if alias:
                aliases = [alias]
        normalized[term] = aliases
    return normalized


def list_rulesets() -> list[str]:
    root = _ruleset_root()
    if not root.exists():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and str(entry.name or "").strip()
    )


def ruleset_exists(name: str) -> bool:
    candidate = str(name or "").strip()
    if not candidate:
        return False
    return (_ruleset_root() / candidate).is_dir()


def write_glossary_candidates(name: str, candidates: Iterable[Any]) -> dict[str, Any]:
    ruleset_name = str(name or "").strip()
    base = _ruleset_root() / ruleset_name
    if not ruleset_name or not base.is_dir():
        raise FileNotFoundError(f"Unknown industry ruleset: {ruleset_name or '<empty>'}")

    canonical = _normalize_glossary(_load_yaml(base / _GLOSSARY_FILENAME))
    generated_path = base / "glossary.generated.yaml"
    generated = _normalize_glossary(_load_yaml(generated_path))

    tokens: list[str] = []
    seen: set[str] = set()
    for item in candidates or []:
        token = str((item or {}).get("token") if isinstance(item, dict) else item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)

    added: list[str] = []
    skipped: list[str] = []
    for token in tokens:
        if token in canonical or token in generated:
            skipped.append(token)
            continue
        generated[token] = []
        added.append(token)

    if added:
        generated_path.write_text(
            yaml.safe_dump(dict(sorted(generated.items())), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    return {
        "ruleset": ruleset_name,
        "candidate_count": int(len(tokens)),
        "added_count": int(len(added)),
        "skipped_count": int(len(skipped)),
        "added_tokens": added,
        "skipped_tokens": skipped,
        "generated_path": str(generated_path),
    }


def replace_ruleset_glossary(name: str, glossary: Any) -> dict[str, Any]:
    ruleset_name = str(name or "").strip()
    base = _ruleset_root() / ruleset_name
    if not ruleset_name or not base.is_dir():
        raise FileNotFoundError(f"Unknown industry ruleset: {ruleset_name or '<empty>'}")
    normalized = dict(sorted(_normalize_glossary(glossary).items()))
    _write_yaml(base / _GLOSSARY_FILENAME, normalized)
    return {"ruleset": ruleset_name, "section": "glossary", "updated_count": int(len(normalized))}


def replace_ruleset_patterns(name: str, patterns: Any) -> dict[str, Any]:
    ruleset_name = str(name or "").strip()
    base = _ruleset_root() / ruleset_name
    if not ruleset_name or not base.is_dir():
        raise FileNotFoundError(f"Unknown industry ruleset: {ruleset_name or '<empty>'}")
    normalized = [dict(item) for item in (patterns or []) if isinstance(item, dict)]
    _write_yaml(base / "patterns.yaml", normalized)
    return {"ruleset": ruleset_name, "section": "patterns", "updated_count": int(len(normalized))}


def replace_ruleset_intents(name: str, intents: Any) -> dict[str, Any]:
    ruleset_name = str(name or "").strip()
    base = _ruleset_root() / ruleset_name
    if not ruleset_name or not base.is_dir():
        raise FileNotFoundError(f"Unknown industry ruleset: {ruleset_name or '<empty>'}")
    normalized = [dict(item) for item in (intents or []) if isinstance(item, dict)]
    _write_yaml(base / "intents.yaml", normalized)
    return {"ruleset": ruleset_name, "section": "intents", "updated_count": int(len(normalized))}


def load_ruleset(name: str) -> IndustryRuleset:
    base = _ruleset_root() / str(name or "").strip()
    glossary = _normalize_glossary(_load_yaml(base / _GLOSSARY_FILENAME))
    generated_glossary = _normalize_glossary(_load_yaml(base / "glossary.generated.yaml"))
    patterns = _load_yaml(base / "patterns.yaml")
    intents = _load_yaml(base / "intents.yaml")
    if not isinstance(patterns, list):
        patterns = []
    if not isinstance(intents, list):
        intents = []
    merged_glossary = dict(glossary)
    for term, aliases in generated_glossary.items():
        if term not in merged_glossary:
            merged_glossary[term] = list(aliases)
    return IndustryRuleset(
        name=str(name or "").strip(),
        glossary=merged_glossary,
        patterns=[dict(item) for item in patterns if isinstance(item, dict)],
        intents=[dict(item) for item in intents if isinstance(item, dict)],
    )
