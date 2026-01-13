"""
Markdown governance processor shared by parsing and indexing pipelines.
"""

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from langchain_core.documents import Document

from app.rag.preprocessing.cleaning import (
    clean_markdown,
    RegexRule,
    build_common_line_signatures,
    build_repeated_line_signatures,
)
from app.rag.preprocessing.boilerplate import remove_markdown_boilerplate
from app.rag.preprocessing.images import strip_images
from app.rag.preprocessing.pii_anonymizer import anonymize_pii
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES
from app.rag.preprocessing.quality_filters import drop_if_low_density, drop_if_outline_only


@dataclass(frozen=True)
class GovernanceStats:
    documents: int
    changed: int
    applied_rules: int
    dropped: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)


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
        remove_boilerplate: bool = False,
        remove_images: str = "none",
        pii_anonymize: bool = False,
        pii_mode: str = "mask",
        pii_mask: str = "[REDACTED]",
        max_blank_lines: int = 1,
        drop_outline_only: bool = False,
        drop_outline_min_content_chars: int = 200,
        drop_outline_max_heading_ratio: float = 0.85,
        drop_low_density: bool = False,
        drop_low_density_threshold: float = 0.12,
        collapse_blank_lines: bool = True,
        unwrap_max_line_length: int = 120,
        noise_min_chars: int = 2,
        noise_ratio_threshold: float = 0.2,
        common_lines_min_docs: int = 3,
        common_lines_min_ratio: float = 0.35,
    ) -> tuple[List[Document], GovernanceStats]:
        if not documents:
            return [], GovernanceStats(documents=0, changed=0, applied_rules=0, dropped=0, drop_reasons={})

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
        dropped = 0
        drop_reasons: dict[str, int] = {}

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
                collapse_blank_lines=collapse_blank_lines,
                max_blank_lines=max_blank_lines,
                unwrap_max_line_length=unwrap_max_line_length,
                noise_min_chars=noise_min_chars,
                noise_ratio_threshold=noise_ratio_threshold,
            )
            applied_total += int(result.applied_rules or 0)
            text = result.markdown
            changed_any = bool(result.changed)

            boilerplate = None
            if remove_boilerplate:
                boilerplate = remove_markdown_boilerplate(text)
                text = boilerplate.text
                changed_any = changed_any or bool(boilerplate.changed)

            images_removed = 0
            if str(remove_images or "none").strip().lower() in {"decorative", "all"}:
                img = strip_images(text, mode=str(remove_images).strip().lower())  # type: ignore[arg-type]
                text = img.text
                images_removed = int(img.removed or 0)
                changed_any = changed_any or bool(img.changed)

            pii_hits: dict[str, int] = {}
            if pii_anonymize:
                pii = anonymize_pii(text, enabled=True, mode=str(pii_mode or "mask"), mask=str(pii_mask or "[REDACTED]"))  # type: ignore[arg-type]
                text = pii.text
                pii_hits = dict(pii.hits or {})
                changed_any = changed_any or bool(pii.changed)

            drop_reason: str | None = None
            if drop_outline_only:
                decision = drop_if_outline_only(
                    text,
                    min_content_chars=int(drop_outline_min_content_chars or 0),
                    max_heading_ratio=float(drop_outline_max_heading_ratio or 0.0),
                )
                if decision.dropped:
                    drop_reason = decision.reason or "outline_only"

            if drop_reason is None and drop_low_density:
                decision = drop_if_low_density(text, threshold=float(drop_low_density_threshold or 0.0))
                if decision.dropped:
                    drop_reason = decision.reason or "low_density"

            if drop_reason is not None:
                dropped += 1
                key = str(drop_reason or "dropped")
                drop_reasons[key] = drop_reasons.get(key, 0) + 1
                # Skip this document to avoid producing empty/noisy chunks.
                continue

            if changed_any:
                changed += 1
            meta = dict(doc.metadata or {})
            meta["governance_applied"] = True
            meta["governance_rules_applied"] = int(result.applied_rules or 0)
            meta["governance_changed"] = bool(changed_any)
            if boilerplate is not None:
                meta["governance_boilerplate_removed_sections"] = int(boilerplate.removed_sections or 0)
                meta["governance_boilerplate_removed_lines"] = int(boilerplate.removed_lines or 0)
            if images_removed:
                meta["governance_images_removed"] = int(images_removed)
            if pii_hits:
                meta["governance_pii_hits"] = pii_hits
            cleaned.append(Document(page_content=text, metadata=meta, id=getattr(doc, "id", None)))

        return cleaned, GovernanceStats(
            documents=len(documents),
            changed=changed,
            applied_rules=applied_total,
            dropped=dropped,
            drop_reasons=drop_reasons,
        )


governance_processor = GovernanceProcessor()
