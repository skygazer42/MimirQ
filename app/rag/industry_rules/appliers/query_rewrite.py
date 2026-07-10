
from typing import Mapping, Sequence


def expand_query_terms(query: str, glossary: Mapping[str, Sequence[str]] | None) -> str:
    parts = [str(query or "").strip()]
    current = parts[0]
    for key, values in (glossary or {}).items():
        term = str(key or "").strip()
        if not term or term not in current:
            continue
        for value in values or []:
            alias = str(value or "").strip()
            if alias and alias not in parts:
                parts.append(alias)
    return " ".join(part for part in parts if part)
