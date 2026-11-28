"""Parse model response text and render deterministic abstain and follow-up guidance."""

import json
import re
from collections.abc import Iterable, Iterator
from typing import Any, Literal

from app.rag.retrieval.evidence.validity import NO_CURRENT_EVIDENCE
from app.types.document_metadata import metadata_text


def extract_first_code_fence(text: str, *, allowed_info_strings: Iterable[str] | None = None) -> str | None:
    """
    Extract the first triple-backtick code fence content.

    Args:
        text: Input text, potentially containing fenced blocks.
        allowed_info_strings: Optional allowlist of info strings (language tags)
          to accept. Examples: {"", "json"}, {"", "sql"}.

    Returns:
        The inner fenced content (trimmed), or None if no allowed fence is found.
    """
    raw = text
    if not raw:
        return None

    allowed: set[str] | None = None
    if allowed_info_strings is not None:
        allowed = {(s).strip().lower() for s in allowed_info_strings}

    start = raw.find("```")
    while start != -1:
        # Determine the opening fence's info string (until newline/end).
        line_end = raw.find("\n", start + 3)
        if line_end == -1:
            line_end = len(raw)
        info = raw[start + 3 : line_end].strip().lower()
        content_start = line_end + 1 if line_end < len(raw) else line_end
        end = raw.find("```", content_start)
        if end == -1:
            return None
        if allowed is not None and info not in allowed:
            start = raw.find("```", end + 3)
            continue
        inner = raw[content_start:end].strip()
        return inner or None

    return None


def _extract_string_items_from_lines(text: str, *, max_items: int = 12) -> list[str]:
    max_items = max(1, int(max_items or 0))
    items: list[str] = []
    seen: set[str] = set()
    for raw_line in (text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Strip common list prefixes: "- ", "* ", "1. ", "1) ", "• ".
        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+\s*[.)]\s+", "", line)
        line = line.strip().strip('"').strip("'").strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        items.append(line)
        if len(items) >= max_items:
            break
    return items


def _json_candidates(raw: str) -> Iterator[tuple[str, str]]:
    inner = extract_first_code_fence(raw, allowed_info_strings=("", "json"))
    if inner:
        yield "code_fence", inner
    yield "raw", raw

    obj_start = raw.find("{")
    obj_end = raw.rfind("}")
    if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
        yield "first_last_brace", raw[obj_start : obj_end + 1].strip()

    arr_start = raw.find("[")
    arr_end = raw.rfind("]")
    if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
        yield "first_last_bracket", raw[arr_start : arr_end + 1].strip()


def _wrapped_json_array(data: dict[str, Any], *, method: str) -> tuple[Any | None, dict[str, Any] | None]:
    for key in ("items", "queries", "data", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return value, {"ok": True, "method": f"{method}:wrapped:{key}", "error": None}
    list_values = [value for value in data.values() if isinstance(value, list)]
    if len(list_values) == 1:
        return list_values[0], {"ok": True, "method": f"{method}:wrapped:single_list", "error": None}
    return None, None


def _accept_json_candidate(
    data: Any, *, expected: Literal["any", "array", "object"], method: str
) -> tuple[Any | None, dict[str, Any] | None, str | None]:
    if expected == "any":
        return data, {"ok": True, "method": method, "error": None}, None
    if expected == "object":
        if isinstance(data, dict):
            return data, {"ok": True, "method": method, "error": None}, None
        return None, None, f"expected_object_got_{type(data).__name__}"
    if isinstance(data, list):
        return data, {"ok": True, "method": method, "error": None}, None
    if isinstance(data, dict):
        wrapped, meta = _wrapped_json_array(data, method=method)
        if meta is not None:
            return wrapped, meta, None
    return None, None, f"expected_array_got_{type(data).__name__}"


def parse_json_from_text(
    text: str,
    *,
    expected: Literal["any", "array", "object"] = "any",
) -> tuple[Any | None, dict[str, Any]]:
    """
    Best-effort JSON parser for LLM outputs.

    Returns: (data, meta) where meta contains ok/method/error.
    """
    raw = (text).strip()
    if not raw:
        return None, {"ok": False, "method": None, "error": "empty"}

    last_error: str | None = None
    decoded_candidate = False
    for method, candidate in _json_candidates(raw):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = str(exc)[:200]
            continue
        decoded_candidate = True
        accepted, meta, error = _accept_json_candidate(data, expected=expected, method=method)
        if meta is not None:
            return accepted, meta
        last_error = error

    if expected == "array" and not decoded_candidate:
        items = _extract_string_items_from_lines(raw, max_items=12)
        if items:
            return items, {"ok": True, "method": "lines", "error": None}

    return None, {"ok": False, "method": None, "error": last_error or "invalid_json"}


def _abstain_followup_options(citations: list[dict[str, Any]] | None, *, max_options: int) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for citation in _iter_citation_dicts(citations):
        document_id = citation.get("document_id")
        name = citation.get("document_name") or citation.get("source")
        key = str(document_id or name or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        options.append(_citation_followup_option(document_id=document_id, name=name))
        if max_options and len(options) >= max_options:
            break
    return options


def _iter_citation_dicts(citations: list[dict[str, Any]] | None) -> Iterator[dict[str, Any]]:
    for citation in (citations or []) if isinstance(citations, list) else []:
        if isinstance(citation, dict):
            yield citation


def build_abstain_answer_message(reason: str | None) -> str:
    if reason == NO_CURRENT_EVIDENCE:
        return "未找到当前有效的证据，暂时无法确认。"
    if str(reason or "").strip() == "out_of_scope":
        return "This question appears to be outside the current knowledge base."
    return "Unable to answer this question based on the available materials."


def _followup_questions_from_options(raw_options: Any, *, limit: int) -> list[str]:
    followups: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw_options, list):
        return followups
    for option in raw_options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("document_name") or option.get("document_id") or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        followups.append(f'Ask specifically about "{label}".')
        if limit and len(followups) >= limit:
            break
    return followups


def derive_followup_questions(
    abstain_followup: dict[str, Any] | None,
    *,
    max_questions: int = 3,
) -> list[str]:
    """Derive deterministic user-facing follow-up questions from abstain metadata."""
    if not isinstance(abstain_followup, dict):
        return []

    limit = max(0, int(max_questions or 0))
    question = str(abstain_followup.get("question") or "").strip()
    followups = _followup_questions_from_options(abstain_followup.get("options"), limit=limit)
    if followups:
        return followups

    return [question] if question else []


def _extract_followup_tags(raw: str, *, max_items: int) -> tuple[list[str], list[str], bool]:
    open_tag = "<followup>"
    close_tag = "</followup>"
    lower = raw.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))
    limit = max(0, int(max_items or 0))
    questions: list[str] = []
    seen: set[str] = set()
    cleaned_parts: list[str] = []
    cursor = 0
    found_tag = False

    while True:
        start = lower.find(open_tag, cursor)
        if start == -1:
            cleaned_parts.append(raw[cursor:])
            break

        end = lower.find(close_tag, start + len(open_tag))
        if end == -1:
            cleaned_parts.append(raw[cursor:])
            break

        found_tag = True
        cleaned_parts.append(raw[cursor:start])
        question = " ".join(raw[start + len(open_tag) : end].split())
        key = question.casefold()
        if question and key not in seen and (not limit or len(questions) < limit):
            seen.add(key)
            questions.append(question)
        cursor = end + len(close_tag)

    return cleaned_parts, questions, found_tag


def _normalize_followup_body(cleaned_parts: list[str]) -> str:
    normalized_lines: list[str] = []
    pending_blank = False
    for line in "".join(cleaned_parts).splitlines():
        stripped = line.strip()
        if stripped:
            if pending_blank and normalized_lines:
                normalized_lines.append("")
            normalized_lines.append(stripped)
            pending_blank = False
        else:
            pending_blank = True
    return "\n".join(normalized_lines).strip()


def extract_followup_questions_from_answer(
    answer: str | None,
    *,
    max_items: int = 3,
) -> tuple[str, list[str]]:
    """Extract repeated <followup> tags from an answer and return clean body + questions."""
    raw = str(answer or "")
    cleaned_parts, questions, found_tag = _extract_followup_tags(raw, max_items=max_items)
    if not found_tag:
        return raw, []

    return _normalize_followup_body(cleaned_parts), questions


def _abstain_followup_response(reason: str, options: list[dict[str, Any]]) -> dict[str, Any]:
    if reason == "citations_lt_min":
        return {
            "type": "refine_query",
            "question": (
                "No sufficient evidence was retrieved. Please refine the question or provide more relevant documents."
            ),
            "options": [],
        }
    if reason == "out_of_scope":
        return {
            "type": "refine_query",
            "question": (
                "This question appears to be outside the current knowledge base. Please add relevant "
                "materials or narrow the scope."
            ),
            "options": [],
        }
    return {
        "type": "select_document" if options else "refine_query",
        "question": "I found related materials but not enough to answer confidently. Which document should I focus on?",
        "options": options,
    }


def build_abstain_followup(
    *,
    reason: str | None,
    citations: list[dict[str, Any]] | None = None,
    max_options: int = 3,
) -> dict[str, Any]:
    """Build follow-up guidance from answer citation identity values."""
    max_options = max(0, int(max_options or 0))
    options = _abstain_followup_options(citations, max_options=max_options)
    return _abstain_followup_response(str(reason or "").strip(), options)


def _citation_followup_identity(citation: dict[str, Any]) -> tuple[Any, Any, str | None]:
    document_id = citation.get("document_id")
    name = citation.get("document_name") or citation.get("source")
    key = (
        metadata_text(citation, "document_id")
        or metadata_text(citation, "document_name")
        or metadata_text(citation, "source")
    )
    return document_id, name, key


def _citation_followup_option(*, document_id: Any, name: Any) -> dict[str, Any]:
    return {
        "document_id": str(document_id) if document_id is not None else None,
        "document_name": str(name) if name is not None else None,
    }


def _retrieval_abstain_followup_options(
    citations: list[dict[str, Any]] | None, *, max_options: int
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for citation in _iter_citation_dicts(citations):
        document_id, name, key = _citation_followup_identity(citation)
        if not key or key in seen:
            continue
        seen.add(key)
        options.append(_citation_followup_option(document_id=document_id, name=name))
        if max_options and len(options) >= max_options:
            break
    return options


def build_retrieval_abstain_followup(
    *,
    reason: str | None,
    citations: list[dict[str, Any]] | None = None,
    max_options: int = 3,
) -> dict[str, Any]:
    """Build retrieval follow-up guidance using the first nonblank citation metadata identity."""
    max_options = max(0, int(max_options or 0))
    options = _retrieval_abstain_followup_options(citations, max_options=max_options)
    return _abstain_followup_response(str((reason if reason is not None else "")).strip(), options)


__all__ = [
    "extract_first_code_fence",
    "parse_json_from_text",
    "build_abstain_followup",
    "build_retrieval_abstain_followup",
    "build_abstain_answer_message",
    "derive_followup_questions",
    "extract_followup_questions_from_answer",
]
