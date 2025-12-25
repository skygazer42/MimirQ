"""
Markdown governance processor shared by parsing and indexing pipelines.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from langchain_core.documents import Document

from app.governance.cleaning import clean_markdown, RegexRule, build_common_line_signatures
from app.governance.rules import DEFAULT_MARKDOWN_RULES


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
    ) -> tuple[List[Document], GovernanceStats]:
        if not documents:
            return [], GovernanceStats(documents=0, changed=0, applied_rules=0)

        active_rules = list(rules) if rules is not None else self._rules
        common_lines = build_common_line_signatures([doc.page_content or "" for doc in documents])
        cleaned: List[Document] = []
        changed = 0
        applied_total = 0

        for doc in documents:
            result = clean_markdown(
                doc.page_content or "",
                rules=active_rules,
                common_lines=common_lines,
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
