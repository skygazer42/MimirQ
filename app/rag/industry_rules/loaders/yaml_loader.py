from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.rag.industry_rules.schema import IndustryRuleset


def _ruleset_root() -> Path:
    return Path(__file__).resolve().parents[1] / "rulesets"


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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


def load_ruleset(name: str) -> IndustryRuleset:
    base = _ruleset_root() / str(name or "").strip()
    glossary = _load_yaml(base / "glossary.yaml")
    patterns = _load_yaml(base / "patterns.yaml")
    intents = _load_yaml(base / "intents.yaml")
    if not isinstance(glossary, dict):
        glossary = {}
    if not isinstance(patterns, list):
        patterns = []
    if not isinstance(intents, list):
        intents = []
    normalized = {
        str(key or "").strip(): [str(item or "").strip() for item in value or [] if str(item or "").strip()]
        for key, value in glossary.items()
        if str(key or "").strip()
    }
    return IndustryRuleset(
        name=str(name or "").strip(),
        glossary=normalized,
        patterns=[dict(item) for item in patterns if isinstance(item, dict)],
        intents=[dict(item) for item in intents if isinstance(item, dict)],
    )
