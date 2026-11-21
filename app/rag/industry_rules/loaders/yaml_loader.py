import os
import tempfile
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from app.rag.industry_rules.schema import IndustryRuleset

_GLOSSARY_FILENAME = "glossary.yaml"
_RULESET_WRITE_LOCK = threading.Lock()


class RulesetFormatError(ValueError):
    """A present rule section has invalid YAML or an unsupported data shape."""


def _ruleset_root() -> Path:
    return Path(__file__).resolve().parents[1] / "rulesets"


def _ruleset_dir(name: str) -> Path | None:
    candidate = name.strip()
    if not candidate:
        return None
    root = _ruleset_root().resolve()
    base = (root / candidate).resolve()
    return base if base.parent == root else None


def _require_ruleset_dir(name: str) -> Path:
    base = _ruleset_dir(name)
    if base is None or not base.is_dir():
        raise FileNotFoundError(f"Unknown industry ruleset: {name or '<empty>'}")
    return base


def _load_yaml(path: Path, *, default: Any) -> Any:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise RulesetFormatError(f"Invalid YAML in industry rules section {path.name}") from error
    return default if value is None else value


def _write_yaml(path: Path, payload: Any) -> None:
    content = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


@contextmanager
def _ruleset_write_lock(base: Path) -> Iterator[None]:
    with _RULESET_WRITE_LOCK:
        if os.name != "posix":  # pragma: no cover - CI and deployments are POSIX
            yield
            return

        import fcntl

        # The lock file remains stable while atomic replacements swap the data-file inodes.
        with (base / ".write.lock").open("a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _normalize_glossary(glossary: Any) -> dict[str, list[str]]:
    if not isinstance(glossary, Mapping):
        raise RulesetFormatError("Industry glossary must be a mapping")
    normalized: dict[str, list[str]] = {}
    for key, value in glossary.items():
        if not isinstance(key, str):
            raise RulesetFormatError("Industry glossary terms must be strings")
        term = key.strip()
        if not term:
            raise RulesetFormatError("Industry glossary terms must not be blank")
        aliases: list[str] = []
        if isinstance(value, (list, tuple)):
            for item in value:
                if not isinstance(item, str):
                    raise RulesetFormatError("Industry glossary aliases must be strings")
                alias = item.strip()
                if alias:
                    aliases.append(alias)
        elif isinstance(value, str):
            alias = value.strip()
            if alias:
                aliases = [alias]
        elif value is not None:
            raise RulesetFormatError("Industry glossary aliases must be strings or a sequence of strings")
        normalized[term] = aliases
    return normalized


def _normalize_rule_rows(rows: Any, *, section: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or any(not isinstance(item, Mapping) for item in rows):
        raise RulesetFormatError(f"Industry {section} must be a list of mappings")
    return [dict(item) for item in rows]


def list_rulesets() -> list[str]:
    root = _ruleset_root()
    if not root.exists():
        return []
    return sorted(entry.name for entry in root.iterdir() if entry.is_dir() and _ruleset_dir(entry.name) is not None)


def ruleset_exists(name: str) -> bool:
    base = _ruleset_dir(name)
    return base is not None and base.is_dir()


def write_glossary_candidates(name: str, candidates: Iterable[Any]) -> dict[str, Any]:
    ruleset_name = name.strip()
    base = _require_ruleset_dir(ruleset_name)

    tokens: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        raw_token = item["token"] if isinstance(item, Mapping) else item
        if not isinstance(raw_token, str):
            raise RulesetFormatError("Glossary candidate tokens must be strings")
        token = raw_token.strip()
        if not token:
            raise RulesetFormatError("Glossary candidate tokens must not be blank")
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)

    generated_path = base / "glossary.generated.yaml"
    with _ruleset_write_lock(base):
        canonical = _normalize_glossary(_load_yaml(base / _GLOSSARY_FILENAME, default={}))
        generated = _normalize_glossary(_load_yaml(generated_path, default={}))
        added: list[str] = []
        skipped: list[str] = []
        for token in tokens:
            if token in canonical or token in generated:
                skipped.append(token)
                continue
            generated[token] = []
            added.append(token)

        if added:
            _write_yaml(generated_path, dict(sorted(generated.items())))

    return {
        "ruleset": ruleset_name,
        "candidate_count": len(tokens),
        "added_count": len(added),
        "skipped_count": len(skipped),
        "added_tokens": added,
        "skipped_tokens": skipped,
        "generated_path": str(generated_path),
    }


def replace_ruleset_glossary(name: str, glossary: Any) -> dict[str, Any]:
    ruleset_name = name.strip()
    base = _require_ruleset_dir(ruleset_name)
    normalized = dict(sorted(_normalize_glossary(glossary).items()))
    with _ruleset_write_lock(base):
        _write_yaml(base / _GLOSSARY_FILENAME, normalized)
    return {"ruleset": ruleset_name, "section": "glossary", "updated_count": len(normalized)}


def replace_ruleset_patterns(name: str, patterns: Any) -> dict[str, Any]:
    ruleset_name = name.strip()
    base = _require_ruleset_dir(ruleset_name)
    normalized = _normalize_rule_rows(patterns, section="patterns")
    with _ruleset_write_lock(base):
        _write_yaml(base / "patterns.yaml", normalized)
    return {"ruleset": ruleset_name, "section": "patterns", "updated_count": len(normalized)}


def replace_ruleset_intents(name: str, intents: Any) -> dict[str, Any]:
    ruleset_name = name.strip()
    base = _require_ruleset_dir(ruleset_name)
    normalized = _normalize_rule_rows(intents, section="intents")
    with _ruleset_write_lock(base):
        _write_yaml(base / "intents.yaml", normalized)
    return {"ruleset": ruleset_name, "section": "intents", "updated_count": len(normalized)}


def load_ruleset(name: str) -> IndustryRuleset:
    base = _require_ruleset_dir(name)
    glossary = _normalize_glossary(_load_yaml(base / _GLOSSARY_FILENAME, default={}))
    generated_glossary = _normalize_glossary(_load_yaml(base / "glossary.generated.yaml", default={}))
    patterns = _normalize_rule_rows(_load_yaml(base / "patterns.yaml", default=[]), section="patterns")
    intents = _normalize_rule_rows(_load_yaml(base / "intents.yaml", default=[]), section="intents")
    merged_glossary = dict(glossary)
    for term, aliases in generated_glossary.items():
        merged_glossary.setdefault(term, aliases)
    return IndustryRuleset(
        name=name.strip(),
        glossary=merged_glossary,
        patterns=patterns,
        intents=intents,
    )
