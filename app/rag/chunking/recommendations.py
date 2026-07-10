
MAINSTREAM_RAG_STRATEGIES: set[str] = {
    "auto",
    "langchain_recursive",
    "semantic_sentence",
    "parent_child",
    "markdown",
    "markdown_header",
    "markdown_hierarchy",
    "text_hierarchy",
    "markdown_table",
    "csv_rows",
    "spreadsheet_sheet",
    "smart_code",
    "json",
    "html_sections",
    "qa_pairs",
    "api_reference",
    "openapi_spec",
    "sql_schema",
    "jira_ticket",
    "laws_structured",
    "paper",
}

EXPERIMENTAL_RAG_STRATEGIES: set[str] = {
    "agentic_chunker",
    "late_chunking",
    "late_chunking_jina",
    "proposition",
    "raptor",
}

OPTIONAL_DEPENDENCY_STRATEGIES: set[str] = {
    "llama_index",
    "llama_index_hierarchical",
}


def decorate_chunk_strategy_note(name: str, notes: str | None) -> str | None:
    strategy = str(name or "").strip().lower()
    note = str(notes or "").strip()
    if not note:
        return None
    if strategy in MAINSTREAM_RAG_STRATEGIES:
        return f"[Mainstream RAG recommended] {note}"
    if strategy in EXPERIMENTAL_RAG_STRATEGIES:
        return f"[Experimental or corpus-specific] {note}"
    if strategy in OPTIONAL_DEPENDENCY_STRATEGIES:
        return f"[Optional dependency] {note}"
    if strategy.startswith("integrated_"):
        return f"[Integrated parse+chunk preset] {note}"
    return f"[Specialized document strategy] {note}"


__all__ = [
    "decorate_chunk_strategy_note",
    "EXPERIMENTAL_RAG_STRATEGIES",
    "MAINSTREAM_RAG_STRATEGIES",
    "OPTIONAL_DEPENDENCY_STRATEGIES",
]
