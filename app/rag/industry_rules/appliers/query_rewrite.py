from collections.abc import Iterator, Mapping, Sequence


def iter_query_aliases(query: str, glossary: Mapping[str, Sequence[str]] | None) -> Iterator[str]:
    current = query.strip()
    seen = {current}
    if glossary is None:
        return
    for key, values in glossary.items():
        term = key.strip()
        if not term or term not in current:
            continue
        for value in values:
            alias = value.strip()
            if alias and alias not in seen:
                seen.add(alias)
                yield alias


def expand_query_terms(query: str, glossary: Mapping[str, Sequence[str]] | None) -> str:
    return " ".join(part for part in [query.strip(), *iter_query_aliases(query, glossary)] if part)
