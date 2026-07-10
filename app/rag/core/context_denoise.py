"""
Prompt context de-noising helpers.

These are applied *after* retrieval but *before* assembling the prompt context.
Goal: reduce duplicated/low-value context tokens without changing the retrieval layer.

Rules:
- deterministic and stable ordering (first occurrence wins)
- conservative cleaning (boilerplate removal is heading/code-fence aware)
"""


import re
from collections import defaultdict
from collections.abc import Iterable

from langchain_core.documents import Document

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string
from app.rag.preprocessing.boilerplate import remove_markdown_boilerplate
from app.rag.preprocessing.normalization import normalize_text

_WS_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_JACCARD_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _normalize_for_signature(text: str) -> str:
    norm = normalize_text(text or "", normalize_line_endings=True, remove_control_chars=True)
    # Keep newlines, but normalize whitespace so "exact duplicates" are caught.
    norm = _WS_RE.sub(" ", norm)
    norm = _BLANK_LINES_RE.sub("\n\n", norm)
    norm = "\n".join([ln.rstrip() for ln in norm.splitlines()])
    return norm.strip()


def _clean_chunk_text(text: str) -> str:
    # Normalize common exporter artifacts first, then remove boilerplate blocks/lines.
    norm = _normalize_for_signature(text)
    if not norm:
        return ""
    return remove_markdown_boilerplate(norm).text.strip()


def _tokenize_for_jaccard(text: str) -> set[str]:
    if not text:
        return set()
    norm = _normalize_for_signature(text)
    if not norm:
        return set()

    raw_tokens = _JACCARD_TOKEN_RE.findall(norm)
    if not raw_tokens:
        return set()

    # For ASCII, ignore 1-char tokens (noise). For non-ASCII, allow 1-char tokens
    # so CJK-heavy text can still be deduped reasonably.
    min_len = 2 if norm.isascii() else 1
    out: set[str] = set()
    for t in raw_tokens:
        if not t:
            continue
        if len(t) < min_len:
            continue
        out.add(t.casefold())
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter <= 0:
        return 0.0
    union = len(a | b)
    return float(inter) / float(union) if union else 0.0


def _doc_group_id(doc: Document) -> str:
    meta = doc.metadata or {}
    raw = meta.get("document_id")
    return str(raw) if raw is not None else ""


def _apply_per_doc_cap(docs: list[Document], *, max_per_doc: int) -> list[Document]:
    if max_per_doc <= 0:
        return docs
    counts: dict[str, int] = defaultdict(int)
    out: list[Document] = []
    for d in docs:
        gid = _doc_group_id(d)
        if gid:
            counts[gid] += 1
            if counts[gid] > max_per_doc:
                continue
        out.append(d)
    return out


def _apply_exact_dedup(docs: list[Document]) -> list[Document]:
    seen: set[str] = set()
    out: list[Document] = []
    for d in docs:
        sig = _normalize_for_signature(d.page_content or "")
        key = sig.casefold() if sig.isascii() else sig
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(d)
    return out


def _apply_jaccard_dedup(
    docs: list[Document],
    *,
    threshold: float,
    max_compare: int,
) -> list[Document]:
    thr = float(threshold or 0.0)
    if not docs or thr <= 0.0:
        return docs

    max_cmp = int(max_compare or 0)
    if max_cmp < 0:
        max_cmp = 0

    out: list[Document] = []
    compare_sets: list[set[str]] = []
    for d in docs:
        tokens = _tokenize_for_jaccard(d.page_content or "")
        if not tokens:
            out.append(d)
            compare_sets.append(tokens)
            continue

        if max_cmp > 0:
            candidates = compare_sets[-max_cmp:]
        else:
            candidates = compare_sets

        is_dup = any(_jaccard(tokens, prev) >= thr for prev in candidates if prev)
        if is_dup:
            continue

        out.append(d)
        compare_sets.append(tokens)

    return out


def _apply_lost_in_middle_reorder(docs: list[Document]) -> list[Document]:
    if not docs:
        return docs
    try:
        from app.rag.core.doc_ordering import reorder_docs_for_generation

        return reorder_docs_for_generation(docs)
    except Exception:
        return docs


def _apply_token_budget_trim(docs: list[Document], *, max_total_tokens: int) -> list[Document]:
    cap = int(max_total_tokens or 0)
    if cap <= 0 or not docs:
        return docs

    out: list[Document] = []
    used = 0
    for doc in docs:
        content = str(getattr(doc, "page_content", "") or "").strip()
        if not content:
            continue
        n = int(num_tokens_from_string(content) or 0)
        if out and (used + n) > cap:
            break
        out.append(doc)
        used += max(0, n)
    return out


def _compress_text_with_llm(*, text: str, query: str, target_ratio: float) -> str:
    if not text or not query:
        return text

    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    from app.rag.engine import get_rag_engine

    engine = get_rag_engine()
    llm = engine.models.get("fast") or engine.models.get("default")
    if llm is None:
        return text

    ratio = float(target_ratio or 0.0)
    if ratio <= 0.0:
        ratio = 0.5

    prompt = ChatPromptTemplate.from_template(
        """Extract only the information relevant to the query from the following text.
Keep key facts, numbers, and relationships. Remove filler and irrelevant details.

Query: {query}
Text:
{text}

Relevant information:"""
    )
    chain = prompt | llm.bind(temperature=0.0) | StrOutputParser()
    try:
        out = chain.invoke({"query": query, "text": text})
    except Exception:
        return text
    compressed = str(out or "").strip()
    if not compressed:
        return text
    return compressed


def compress_context_docs_with_llm(
    docs: Iterable[Document] | None,
    *,
    query: str | None = None,
) -> list[Document]:
    if not docs:
        return []
    if not bool(getattr(settings, "RAG_CONTEXT_LLM_COMPRESSION_ENABLED", False)):
        return list(docs)

    query_text = str(query or "").strip()
    if not query_text:
        return list(docs)

    ratio = float(getattr(settings, "RAG_CONTEXT_LLM_COMPRESSION_TARGET_RATIO", 0.5) or 0.5)
    ratio = min(max(ratio, 0.1), 1.0)

    out: list[Document] = []
    for doc in docs:
        if doc is None:
            continue
        text = str(getattr(doc, "page_content", "") or "").strip()
        if not text:
            continue
        compressed = _compress_text_with_llm(text=text, query=query_text, target_ratio=ratio)
        out.append(Document(page_content=compressed, metadata=dict(doc.metadata or {}), id=getattr(doc, "id", None)))
    return out


def denoise_context_docs(docs: Iterable[Document] | None) -> list[Document]:
    """
    Clean and deduplicate retrieved context docs before prompt assembly.

    Applies:
    - boilerplate removal (conservative)
    - exact-duplicate dropping
    - near-duplicate dropping (jaccard)
    - per-document cap (stable)
    """
    if not docs:
        return []

    # 1) Clean page_content conservatively; keep metadata/id stable.
    cleaned: list[Document] = []
    for d in docs:
        if d is None:
            continue
        text = _clean_chunk_text(getattr(d, "page_content", "") or "")
        if not text:
            continue
        cleaned.append(Document(page_content=text, metadata=dict(d.metadata or {}), id=getattr(d, "id", None)))

    if not cleaned:
        return []

    # 2) Drop duplicates before applying caps so we don't "waste" per-doc budget on repeats.
    cleaned = _apply_exact_dedup(cleaned)

    dedup_enabled = bool(getattr(settings, "RETRIEVAL_DEDUP_ENABLED", False))
    if dedup_enabled:
        cleaned = _apply_jaccard_dedup(
            cleaned,
            threshold=float(getattr(settings, "RETRIEVAL_DEDUP_JACCARD_THRESHOLD", 0.0) or 0.0),
            max_compare=int(getattr(settings, "RETRIEVAL_DEDUP_MAX_COMPARE", 0) or 0),
        )

    # 3) Per-doc cap (reuse retrieval knob; prompt context needs the same diversity guard after injections).
    max_per_doc = int(getattr(settings, "RETRIEVAL_MAX_CHUNKS_PER_DOC", 0) or 0)
    cleaned = _apply_per_doc_cap(cleaned, max_per_doc=max_per_doc)

    # 4) Optional lost-in-middle mitigation via deterministic interleaving.
    if bool(getattr(settings, "RAG_CONTEXT_LOST_IN_MIDDLE_REORDER_ENABLED", False)):
        cleaned = _apply_lost_in_middle_reorder(cleaned)

    # 5) Optional token-budget-aware trim for pre-prompt context packing.
    if bool(getattr(settings, "RAG_CONTEXT_TOKEN_BUDGET_TRIM_ENABLED", False)):
        cleaned = _apply_token_budget_trim(
            cleaned,
            max_total_tokens=int(getattr(settings, "RAG_CONTEXT_DENOISE_MAX_TOTAL_TOKENS", 0) or 0),
        )

    return cleaned


__all__ = [
    "compress_context_docs_with_llm",
    "denoise_context_docs",
]
