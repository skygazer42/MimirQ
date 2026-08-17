
from typing import Any
from urllib.parse import urlencode


def _build_inline_citation_href(ev: dict[str, Any]) -> str | None:
    doc_id = str(ev.get("document_id") or "").strip()
    chunk_id = str(ev.get("chunk_id") or "").strip()
    page = ev.get("page_number")
    if page is None:
        page = ev.get("page")

    params: dict[str, str] = {}
    if doc_id:
        params["document_id"] = doc_id
    if chunk_id:
        params["chunk_id"] = chunk_id
    try:
        page_i = int(page) if page is not None else None
    except Exception:
        page_i = None
    if page_i is not None:
        params["page"] = str(page_i)
    if not params:
        return None
    return f"mimirq-citation://evidence?{urlencode(params)}"


def _build_markdown_citation_label(ev: dict[str, Any]) -> str | None:
    doc_id = str(ev.get("document_id") or "").strip()
    chunk_id = str(ev.get("chunk_id") or "").strip()
    page = ev.get("page_number")
    if page is None:
        page = ev.get("page")

    parts: list[str] = []
    if doc_id:
        parts.append(f"doc:{doc_id}")
    if chunk_id:
        parts.append(f"chunk:{chunk_id}")
    try:
        page_i = int(page) if page is not None else None
    except Exception:
        page_i = None
    if page_i is not None:
        parts.append(f"p.{page_i}")
    if not parts:
        return None
    return "[" + " | ".join(parts) + "]"


def _render_markdown_evidence(
    evidence: Any,
    *,
    max_evidence_per_claim: int,
) -> list[str]:
    evidence_list = evidence if isinstance(evidence, list) else []
    cites: list[str] = []
    for ev in evidence_list:
        if not isinstance(ev, dict):
            continue
        label = _build_markdown_citation_label(ev)
        if not label:
            continue
        cites.append(label)
        if len(cites) >= max_evidence_per_claim:
            break
    return cites


def _render_sentence_citation_rows(
    *,
    claim_evidence: list[dict[str, Any]] | None,
    max_items: int,
    max_evidence_per_claim: int,
) -> list[str]:
    rows: list[str] = []
    for item in claim_evidence or []:
        if len(rows) >= max_items:
            break
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        if not claim:
            continue

        cites = _render_markdown_evidence(
            item.get("evidence"),
            max_evidence_per_claim=max_evidence_per_claim,
        )
        rows.append(f"- {claim} [no_evidence]" if not cites else f"- {claim} {' '.join(cites)}")
    return rows


def render_sentence_citations_markdown(
    claim_evidence: list[dict[str, Any]] | None,
    *,
    max_items: int = 8,
    max_evidence_per_claim: int = 2,
) -> tuple[str, int]:
    """
    Render sentence-level citation mapping as a compact markdown appendix.

    Returns:
    - markdown suffix (empty when nothing is renderable)
    - number of sentence rows rendered
    """
    max_items = max(0, int(max_items or 0))
    max_evidence_per_claim = max(1, int(max_evidence_per_claim or 0))
    if max_items <= 0:
        return "", 0

    rows = _render_sentence_citation_rows(
        claim_evidence=claim_evidence,
        max_items=max_items,
        max_evidence_per_claim=max_evidence_per_claim,
    )

    if not rows:
        return "", 0

    suffix = "\n\n---\n\n### Sentence Citations\n" + "\n".join(rows) + "\n"
    return suffix, len(rows)


def render_sentence_citations_inline(
    claim_evidence: list[dict[str, Any]] | None,
    *,
    max_items: int = 8,
    max_evidence_per_claim: int = 2,
) -> tuple[str, int]:
    """
    Render sentence-level citations as inline brackets, one claim per line.

    Intended usage:
    - Only when the answer is already "claim-list-like" (e.g., post claim-check),
      otherwise this will lose original formatting.

    Returns:
    - rendered text (empty when nothing is renderable)
    - number of claim rows rendered
    """
    max_items = max(0, int(max_items or 0))
    max_evidence_per_claim = max(1, int(max_evidence_per_claim or 0))
    if max_items <= 0:
        return "", 0

    lines: list[str] = []
    rendered = 0
    reference_number = 0
    for item in claim_evidence or []:
        if rendered >= max_items:
            break
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        if not claim:
            continue

        evidence = item.get("evidence")
        evidence = evidence if isinstance(evidence, list) else []
        cites: list[str] = []
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            href = _build_inline_citation_href(ev)
            if not href:
                continue
            reference_number += 1
            cites.append(f"[{reference_number}]({href})")
            if len(cites) >= max_evidence_per_claim:
                break

        line = claim if not cites else f"{claim} {' '.join(cites)}"
        lines.append(line)
        rendered += 1

    text = "\n".join(lines).strip()
    return (text, rendered) if text else ("", 0)


__all__ = [
    "render_sentence_citations_inline",
    "render_sentence_citations_markdown",
]
