
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml

from app.rag.industry_rules.schema import IndustryRuleset

_GLOSSARY_FILENAME = "glossary.yaml"
_RULESET_WRITE_LOCK = threading.Lock()


def _ruleset_root() -> Path:
    return Path(__file__).resolve().parents[1] / "rulesets"


def _ruleset_dir(name: str) -> Path | None:
    candidate = str(name or "").strip()
    if not candidate:
        return None
    root = _ruleset_root().resolve()
    base = (root / candidate).resolve()
    return base if base.parent == root else None


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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
        if entry.is_dir() and _ruleset_dir(entry.name) is not None
    )


def ruleset_exists(name: str) -> bool:
    base = _ruleset_dir(name)
    return bool(base is not None and base.is_dir())


def write_glossary_candidates(name: str, candidates: Iterable[Any]) -> dict[str, Any]:
    ruleset_name = str(name or "").strip()
    base = _ruleset_dir(ruleset_name)
    if base is None or not base.is_dir():
        raise FileNotFoundError(f"Unknown industry ruleset: {ruleset_name or '<empty>'}")

    tokens: list[str] = []
    seen: set[str] = set()
    for item in candidates or []:
        token = str((item or {}).get("token") if isinstance(item, dict) else item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)

    generated_path = base / "glossary.generated.yaml"
    with _ruleset_write_lock(base):
        canonical = _normalize_glossary(_load_yaml(base / _GLOSSARY_FILENAME))
        generated = _normalize_glossary(_load_yaml(generated_path))
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
        "candidate_count": int(len(tokens)),
        "added_count": int(len(added)),
        "skipped_count": int(len(skipped)),
        "added_tokens": added,
        "skipped_tokens": skipped,
        "generated_path": str(generated_path),
    }


def replace_ruleset_glossary(name: str, glossary: Any) -> dict[str, Any]:
    ruleset_name = str(name or "").strip()
    base = _ruleset_dir(ruleset_name)
    if base is None or not base.is_dir():
        raise FileNotFoundError(f"Unknown industry ruleset: {ruleset_name or '<empty>'}")
    normalized = dict(sorted(_normalize_glossary(glossary).items()))
    with _ruleset_write_lock(base):
        _write_yaml(base / _GLOSSARY_FILENAME, normalized)
    return {"ruleset": ruleset_name, "section": "glossary", "updated_count": int(len(normalized))}


def replace_ruleset_patterns(name: str, patterns: Any) -> dict[str, Any]:
    ruleset_name = str(name or "").strip()
    base = _ruleset_dir(ruleset_name)
    if base is None or not base.is_dir():
        raise FileNotFoundError(f"Unknown industry ruleset: {ruleset_name or '<empty>'}")
    normalized = [dict(item) for item in (patterns or []) if isinstance(item, dict)]
    with _ruleset_write_lock(base):
        _write_yaml(base / "patterns.yaml", normalized)
    return {"ruleset": ruleset_name, "section": "patterns", "updated_count": int(len(normalized))}


def replace_ruleset_intents(name: str, intents: Any) -> dict[str, Any]:
    ruleset_name = str(name or "").strip()
    base = _ruleset_dir(ruleset_name)
    if base is None or not base.is_dir():
        raise FileNotFoundError(f"Unknown industry ruleset: {ruleset_name or '<empty>'}")
    normalized = [dict(item) for item in (intents or []) if isinstance(item, dict)]
    with _ruleset_write_lock(base):
        _write_yaml(base / "intents.yaml", normalized)
    return {"ruleset": ruleset_name, "section": "intents", "updated_count": int(len(normalized))}


def load_ruleset(name: str) -> IndustryRuleset:
    base = _ruleset_dir(name)
    if base is None:
        return IndustryRuleset(name=str(name or "").strip(), glossary={}, patterns=[], intents=[])
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
