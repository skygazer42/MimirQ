"""
Markdown governance processor shared by parsing and indexing pipelines.
"""

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from langchain_core.documents import Document

from app.rag.preprocessing.cleaning import (
    clean_markdown,
    RegexRule,
    build_common_line_signatures,
    build_repeated_line_signatures,
)
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES


@dataclass(frozen=True)
class GovernanceStats:
    documents: int
    changed: int
    applied_rules: int


class GovernanceProcessor:
    """Apply conservative markdown cleanup rules before chunking."""

    def __init__(self, rules: Optional[Iterable[RegexRule]] = None) -> None:
        self._rules = list(rules) if rules is not None else list(DEFAULT_MARKDOWN_RULES)

    def clean_documents(
        self,
        documents: Sequence[Document],
        *,
        rules: Optional[Iterable[RegexRule]] = None,
        remove_toc_lines: bool = True,
        remove_noise_lines: bool = True,
        unwrap_lines: bool = True,
        remove_common_lines: bool = True,
        unwrap_max_line_length: int = 120,
        noise_min_chars: int = 2,
        noise_ratio_threshold: float = 0.2,
        common_lines_min_docs: int = 3,
        common_lines_min_ratio: float = 0.35,
    ) -> tuple[List[Document], GovernanceStats]:
        if not documents:
            return [], GovernanceStats(documents=0, changed=0, applied_rules=0)

        active_rules = list(rules) if rules is not None else self._rules
        doc_count = len(documents)
        min_docs_eff = max(2, int(common_lines_min_docs or 0))
        if doc_count >= 2:
            min_docs_eff = min(min_docs_eff, doc_count)
        else:
            min_docs_eff = 0
        global_common_lines = (
            build_common_line_signatures(
                [doc.page_content or "" for doc in documents],
                min_docs=min_docs_eff,
                min_ratio=common_lines_min_ratio,
                max_line_length=unwrap_max_line_length,
            )
            if remove_common_lines and min_docs_eff >= 2
            else set()
        )
        cleaned: List[Document] = []
        changed = 0
        applied_total = 0

        for doc in documents:
            local_common_lines = (
                build_repeated_line_signatures(
                    doc.page_content or "",
                    min_occurrences=common_lines_min_docs,
                    max_line_length=unwrap_max_line_length,
                )
                if remove_common_lines
                else set()
            )
            common_lines = (global_common_lines | local_common_lines) if remove_common_lines else None
            result = clean_markdown(
                doc.page_content or "",
                rules=active_rules,
                common_lines=common_lines,
                remove_toc_lines=remove_toc_lines,
                remove_noise_lines=remove_noise_lines,
                unwrap_lines=unwrap_lines,
                remove_common_lines=remove_common_lines,
                unwrap_max_line_length=unwrap_max_line_length,
                noise_min_chars=noise_min_chars,
                noise_ratio_threshold=noise_ratio_threshold,
            )
            applied_total += int(result.applied_rules or 0)
            if result.changed:
                changed += 1
            meta = dict(doc.metadata or {})
            meta["governance_applied"] = True
            meta["governance_rules_applied"] = int(result.applied_rules or 0)
            meta["governance_changed"] = bool(result.changed)
            cleaned.append(Document(page_content=result.markdown, metadata=meta, id=getattr(doc, "id", None)))

        return cleaned, GovernanceStats(
            documents=len(documents),
            changed=changed,
            applied_rules=applied_total,
        )


governance_processor = GovernanceProcessor()
