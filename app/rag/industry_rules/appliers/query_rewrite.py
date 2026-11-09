from collections.abc import Mapping, Sequence


def expand_query_terms(query: str, glossary: Mapping[str, Sequence[str]] | None) -> str:
    parts = [query.strip()]
    current = parts[0]
    for key, values in (glossary or {}).items():
        term = key.strip()
        if not term or term not in current:
            continue
        for value in values or []:
            alias = value.strip()
            if alias and alias not in parts:
                parts.append(alias)
    return " ".join(part for part in parts if part)
