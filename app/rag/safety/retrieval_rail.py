from __future__ import annotations

import re
from typing import Any

from langchain_core.documents import Document

from app.rag.preprocessing.pii_anonymizer import anonymize_pii

_INDIRECT_INJECTION_RE = re.compile(
    r"忽略.*规则|忽略前面|system prompt|developer message|ignore previous|act as root",
    flags=re.IGNORECASE,
)


def apply_retrieval_rail(
    docs: list[Document] | None,
    *,
    mask_pii: bool,
    pii_mask: str = "[REDACTED]",
) -> dict[str, Any]:
    kept: list[Document] = []
    blocked_docs = 0
    masked_docs = 0
    for doc in docs or []:
        text = str(getattr(doc, "page_content", "") or "")
        if _INDIRECT_INJECTION_RE.search(text):
            blocked_docs += 1
            continue
        new_doc = doc
        if mask_pii and text:
            pii = anonymize_pii(text, enabled=True, mode="mask", mask=str(pii_mask or "[REDACTED]"))
            if pii.changed:
                masked_docs += 1
                metadata = dict(getattr(doc, "metadata", None) or {})
                metadata["retrieval_rail_pii_masked"] = True
                new_doc = Document(page_content=str(pii.text or ""), metadata=metadata, id=getattr(doc, "id", None))
        kept.append(new_doc)

    return {
        "docs": kept,
        "meta": {
            "blocked_docs": int(blocked_docs),
            "masked_docs": int(masked_docs),
            "used": bool(blocked_docs or masked_docs),
        },
    }
